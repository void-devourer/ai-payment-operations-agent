"""Bounded authoritative reads and fenced, immutable observation history."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import time
import uuid

import httpx
from psycopg2.extras import Json

from .jobs import ReadFailure, finish, heartbeat, lock_owned, reserve_request

MAX_REQUESTS = 30
MAX_SECONDS = 20
MAX_PAGES = 5
MAX_ATTEMPTS_PER_PURCHASE = 20


def retry_after(value):
    try:
        seconds = float(value)
    except (TypeError,ValueError):
        try:
            seconds = (parsedate_to_datetime(value)-datetime.now(UTC)).total_seconds()
        except (TypeError,ValueError,OverflowError):
            return None
    return max(1,min(300,seconds)) if seconds==seconds else None


class Reader:
    def __init__(self, app, job):
        self.app,self.job = app,job
        self.count,self.start = 0,time.monotonic()

    def get(self, base, path, purpose, params=None):
        if self.count>=MAX_REQUESTS or time.monotonic()-self.start>=MAX_SECONDS:
            raise ReadFailure("read_budget")
        heartbeat(self.app.state.database,self.job)
        while not reserve_request(self.app.state.database,self.job["workspace_id"],self.job["connection_id"]):
            if time.monotonic()-self.start>=MAX_SECONDS:
                raise ReadFailure("connection_budget",delay=1)
            time.sleep(.05)
        self.count+=1
        if purpose=="stripe":
            connection=self.app.state.settings.stripe.get(self.job["workspace_id"])
            if connection is None or base!="https://api.stripe.com" or not path.startswith("/v1/"):
                raise ReadFailure("stripe_connection_unconfigured",False)
            headers={"Authorization":"Bearer "+connection.read_key,"Stripe-Version":connection.api_version}
        else:
            headers = {"Authorization":"Bearer "+self.app.state.settings.keys[self.job["workspace_id"]][purpose]}
        try:
            remaining=max(.1,min(5,MAX_SECONDS-(time.monotonic()-self.start)))
            with self.app.state.http.stream("GET",base+path,headers=headers,params=params,timeout=remaining) as response:
                if response.status_code==429:
                    delay=retry_after(response.headers.get("Retry-After")) or 2
                    with self.app.state.database.transaction(self.job["workspace_id"]) as cursor:
                        cursor.execute("""UPDATE connections SET next_request_at=greatest(next_request_at,
                            clock_timestamp()+%s*interval '1 second') WHERE connection_id=%s""", (delay,self.job["connection_id"]))
                    raise ReadFailure("provider_throttled",delay=delay)
                if response.status_code>=500:
                    raise ReadFailure("upstream_unavailable")
                if response.status_code in (401,403):
                    raise ReadFailure("permission_denied",False)
                if response.status_code==404:
                    raise ReadFailure("resource_missing")
                if response.status_code!=200:
                    raise ReadFailure("unsupported_response",False)
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>1024*1024 or time.monotonic()-self.start>=MAX_SECONDS:
                        raise ReadFailure("response_budget")
                value=json.loads(raw)
                if not isinstance(value,dict):
                    raise ValueError()
                return value
        except httpx.RequestError:
            raise ReadFailure("network_timeout") from None
        except (ValueError,RecursionError):
            raise ReadFailure("invalid_provider_shape",False) from None


def require(condition):
    if not condition:
        raise ReadFailure("evidence_binding_or_shape",False)


def current_payment(reader, settings, purchase, intent):
    value=reader.get(settings.simulator_url,f"/internal/payments/{intent}","provider")
    require(value.get("payment_intent_id")==intent and value.get("workspace_id")==purchase["workspace_id"]
            and value.get("account_id")==f"sim_acct_{purchase['workspace_id']}"
            and value.get("environment")=="simulated" and value.get("api_version")=="simulator.v1"
            and value.get("customer_id")==purchase["provider_customer_id"]
            and value.get("purchase_id")==purchase["purchase_id"] and value.get("complete") is True)
    require(value.get("status") in {"requires_payment_method","processing","requires_capture","succeeded","failed","canceled"}
            and type(value.get("amount_received_minor")) is int and 0<=value["amount_received_minor"]<=10**12
            and isinstance(value.get("currency"),str) and len(value["currency"])==3
            and type(value.get("reversal_generation")) is int and value["reversal_generation"]>=0)
    return {key:value[key] for key in ("payment_intent_id","status","amount_received_minor","currency","reversal_generation")}


def reversals(reader, settings, intent, kind, generation):
    after=None
    seen=set()
    rows=[]
    for _ in range(MAX_PAGES):
        page=reader.get(settings.simulator_url,f"/internal/payments/{intent}/{kind}","provider",
                        {"limit":20,**({"starting_after":after} if after else {})})
        if page.get("reversal_generation")!=generation:
            raise ReadFailure("reversal_changed")
        require(page.get("payment_intent_id")==intent and page.get("api_version")=="simulator.v1"
                and page.get("complete") is True
                and isinstance(page.get("data"),list) and type(page.get("has_more")) is bool and len(page["data"])<=20)
        for row in page["data"]:
            require(isinstance(row,dict) and isinstance(row.get("id"),str) and row["id"] not in seen
                    and row.get("payment_intent_id")==intent and isinstance(row.get("status"),str))
            seen.add(row["id"])
            rows.append({"id":row["id"],"status":row["status"]})
        if not page["has_more"]:
            return rows
        require(bool(page["data"]))
        after=page["data"][-1]["id"]
    raise ReadFailure("pagination_budget")


def begin(database,job):
    with database.transaction(job["workspace_id"]) as cursor:
        lock_owned(cursor,job)
        cursor.execute("""SELECT p.* FROM purchases p JOIN payment_attempts a USING(workspace_id,purchase_id)
            WHERE a.connection_id=%s AND a.payment_intent_id=%s""", (job["connection_id"],job["payment_intent_id"]))
        purchase=cursor.fetchone()
        if purchase is None:
            raise ReadFailure("binding_not_registered")
        cursor.execute("SELECT payment_intent_id FROM payment_attempts WHERE purchase_id=%s ORDER BY payment_intent_id", (purchase["purchase_id"],))
        attempts=[row["payment_intent_id"] for row in cursor.fetchall()]
        cursor.execute("""INSERT INTO evidence_heads(workspace_id,purchase_id,generation) VALUES (%s,%s,1)
            ON CONFLICT (workspace_id,purchase_id) DO UPDATE SET generation=evidence_heads.generation+1
            RETURNING generation""", (job["workspace_id"],purchase["purchase_id"]))
        generation=cursor.fetchone()["generation"]
    return dict(purchase),attempts,generation


def publish(database,job,purchase,attempts,generation,facts,started,finished,error=None):
    observation_id=uuid.uuid4().hex
    canonical=json.dumps(facts,sort_keys=True,separators=(",",":"))
    with database.transaction(job["workspace_id"]) as cursor:
        lock_owned(cursor,job)
        # Lock order is jobs -> purchase head, everywhere a projection is written.
        cursor.execute("SELECT generation FROM evidence_heads WHERE purchase_id=%s FOR UPDATE", (purchase["purchase_id"],))
        if cursor.fetchone()["generation"]!=generation:
            raise ReadFailure("observation_superseded")
        cursor.execute("SELECT payment_intent_id FROM payment_attempts WHERE purchase_id=%s ORDER BY payment_intent_id", (purchase["purchase_id"],))
        if [row["payment_intent_id"] for row in cursor.fetchall()]!=attempts:
            raise ReadFailure("attempt_set_changed")
        # A head lock may have waited: recheck expiry before writing incomplete observations too.
        lock_owned(cursor,job)
        cursor.execute("""INSERT INTO observations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (job["workspace_id"],observation_id,purchase["purchase_id"],job["job_id"],generation,Json(facts),
             hashlib.sha256(canonical.encode()).hexdigest(),started,finished,
             "stripe_api_and_target" if facts["scope"]["environment"]=="test" else "simulator_api_and_target",
             facts.get("api_version","simulator.v1"),"evidence_v1"))
        cursor.execute("UPDATE evidence_heads SET observation_id=%s WHERE purchase_id=%s", (observation_id,purchase["purchase_id"]))
        from .detection.projection import apply_observation
        refresh_at=apply_observation(cursor,purchase,attempts,observation_id,facts,finished)
        if error is None:
            finish(cursor,job,refresh_at=refresh_at)
    return observation_id


def collect(app,job):
    purchase,attempts,generation=begin(app.state.database,job)
    settings=app.state.settings
    reader=Reader(app,job)
    stripe_reader=None
    if job["connection_id"].startswith("stripe_"):
        from .stripe_provider import StripeReader
        connection=settings.stripe.get(job["workspace_id"])
        if connection is None or job["connection_id"]!=f"stripe_{job['workspace_id']}":
            raise ReadFailure("stripe_connection_unconfigured",False)
        stripe_reader=StripeReader(reader,connection)
    started=datetime.now(UTC)
    facts={"scope":{"workspace_id":job["workspace_id"],"connection_id":job["connection_id"],
                    "account_id":f"sim_acct_{job['workspace_id']}","environment":"simulated"},
           "registered_attempts":attempts,"payments":[],"refunds":[],"disputes":[],"access":None,
           "payment_complete":False,"reversal_complete":False,"access_complete":False,"financial_complete":False,
           "errors":[],"windows":{}}
    if stripe_reader:
        facts["scope"].update(account_id=connection.account_id,environment="test")
        facts["api_version"]=connection.api_version
    errors=[]
    for bundle in ("payment","reversal","access"):
        window_start=datetime.now(UTC)
        try:
            if bundle=="payment":
                if not attempts or len(attempts)>MAX_ATTEMPTS_PER_PURCHASE:
                    raise ReadFailure("attempt_budget",False)
                if stripe_reader:
                    stripe_reader.verify_account()
                for intent in attempts:
                    facts["payments"].append(stripe_reader.payment(purchase,intent) if stripe_reader
                                             else current_payment(reader,settings,purchase,intent))
            elif bundle=="reversal":
                if not facts["payment_complete"]:
                    raise ReadFailure("payment_incomplete")
                for payment in facts["payments"]:
                    intent=payment["payment_intent_id"]
                    if stripe_reader:
                        refund_rows,dispute_rows=stripe_reader.reversals(payment)
                        facts["refunds"].extend(refund_rows)
                        facts["disputes"].extend(dispute_rows)
                    else:
                        for kind in ("refunds","disputes"):
                            facts[kind].extend(reversals(reader,settings,intent,kind,payment["reversal_generation"]))
            else:
                access=reader.get(settings.reference_url,f"/internal/access/{purchase['purchase_id']}","adapter")
                require(all(access.get(key)==purchase[key] for key in ("workspace_id","purchase_id","customer_id","product_id"))
                        and access.get("complete") is True and access.get("status") in {"inactive","active","suspended","revoked"}
                        and type(access.get("revision")) is int and access["revision"]>=0 and type(access.get("ever_activated")) is bool)
                facts["access"]={key:access[key] for key in ("workspace_id","purchase_id","customer_id","product_id","status","revision","ever_activated")}
            facts[bundle+"_complete"]=True
        except ReadFailure as error:
            errors.append(error)
            facts["errors"].append({"bundle":bundle,"code":error.code})
        facts["windows"][bundle]={"started_at":window_start.isoformat(),"finished_at":datetime.now(UTC).isoformat(),
                                     "complete":facts[bundle+"_complete"]}
    # Prefer a permanent problem over retryable incompleteness; neither can authorize an action.
    error=next((value for value in errors if not value.retryable),errors[0] if errors else None)
    publish(app.state.database,job,purchase,attempts,generation,facts,started,datetime.now(UTC),error)
    if error:
        raise error
