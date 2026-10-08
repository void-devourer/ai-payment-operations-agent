"""Read-only Stripe snapshot contract; no provider mutation exists in this adapter."""

import re

from .config import STRIPE_API_VERSION
from .jobs import ReadFailure

API_BASE="https://api.stripe.com"
MAX_PAGES=5
PAGE_SIZE=20
EVENT_TYPES={"payment_intent.succeeded","payment_intent.processing","payment_intent.payment_failed",
             "payment_intent.canceled","payment_intent.amount_capturable_updated","charge.refunded",
             "refund.created","refund.updated","refund.failed","charge.dispute.created",
             "charge.dispute.updated","charge.dispute.closed"}


def require(condition):
    if not condition:
        raise ReadFailure("stripe_scope_or_shape",False)


def object_id(value,prefix):
    if isinstance(value,dict):
        value=value.get("id")
    require(isinstance(value,str) and re.fullmatch(prefix+r"[A-Za-z0-9]{1,100}",value) is not None)
    return value


def configure_connections(database,settings):
    for workspace,connection in settings.stripe.items():
        with database.transaction(workspace) as cursor:
            cursor.execute("""INSERT INTO connections(workspace_id,connection_id,account_id,environment,api_version,provider)
                VALUES (%s,%s,%s,'test',%s,'stripe') ON CONFLICT DO NOTHING""",
                (workspace,f"stripe_{workspace}",connection.account_id,connection.api_version))
            cursor.execute("SELECT account_id,environment,api_version,provider FROM connections WHERE connection_id=%s", (f"stripe_{workspace}",))
            if dict(cursor.fetchone())!={"account_id":connection.account_id,"environment":"test",
                                        "api_version":connection.api_version,"provider":"stripe"}:
                raise ValueError("Stripe connection is immutable; existing account/version conflicts")


def parse_stripe_event(raw,connection):
    from .ingestion import decode_json,identifier
    event=decode_json(raw)
    if not isinstance(event,dict) or event.get("object")!="event" or event.get("livemode") is not False:
        raise ValueError("invalid_stripe_envelope")
    identifier.validate_python(event.get("id"))
    if not event["id"].startswith("evt_") or type(event.get("created")) is not int or event["created"]<0:
        raise ValueError("invalid_stripe_envelope")
    # Direct account events usually omit account; supplied Connect context must match.
    if event.get("account") not in (None,connection.account_id) or event.get("context") is not None:
        raise ValueError("stripe_account_mismatch")
    for field in ("type","api_version"):
        if not isinstance(event.get(field),str) or not 1<=len(event[field])<=100:
            raise ValueError("invalid_stripe_envelope")
    if event["api_version"]!=connection.api_version:
        return event,"quarantined",None
    if event["type"] not in EVENT_TYPES:
        return event,"ignored",None
    resource=event.get("data",{}).get("object",{})
    if not isinstance(resource,dict) or (resource.get("livemode") is not False and
            not (event["type"].startswith("refund.") and "livemode" not in resource)):
        raise ValueError("invalid_stripe_resource")
    try:
        intent=object_id(resource.get("id") if event["type"].startswith("payment_intent.") else resource.get("payment_intent"),"pi_")
    except ReadFailure:
        raise ValueError("missing_payment_intent_binding") from None
    return event,"accepted",intent


class StripeReader:
    def __init__(self,reader,connection):
        self.reader,self.connection=reader,connection

    def get(self,path,params=None):
        # Fixed origin and explicit resource paths, with credentials never placed in URLs.
        return self.reader.get(API_BASE,path,"stripe",params)

    def verify_account(self):
        account=self.get("/v1/account")
        require(account.get("object")=="account" and account.get("id")==self.connection.account_id)

    def payment(self,purchase,intent):
        object_id(intent,"pi_")
        value=self.get("/v1/payment_intents/"+intent)
        require(value.get("id")==intent and value.get("object")=="payment_intent" and value.get("livemode") is False)
        require(object_id(value.get("customer"),"cus_")==purchase["provider_customer_id"])
        metadata=value.get("metadata")
        require(isinstance(metadata,dict))
        # Metadata is a consistency check only; trusted registration remains the authority.
        if "purchase_id" in metadata:
            require(metadata["purchase_id"]==purchase["purchase_id"])
        require(value.get("status") in {"requires_payment_method","requires_confirmation","requires_action",
                "processing","requires_capture","canceled","succeeded"}
                and type(value.get("amount_received")) is int and 0<=value["amount_received"]<=10**12
                and isinstance(value.get("currency"),str) and re.fullmatch(r"[a-z]{3}",value["currency"]) is not None)
        latest=value.get("latest_charge")
        if latest is not None:
            latest=object_id(latest,"ch_")
        if value["status"]=="succeeded":
            require(latest is not None)
        return {"payment_intent_id":intent,"status":value["status"],"amount_received_minor":value["amount_received"],
                "currency":value["currency"],"latest_charge":latest}

    def pages(self,path,params,prefix,intent):
        rows=[]
        seen=set()
        after=None
        for _ in range(MAX_PAGES):
            page=self.get(path,{**params,"limit":PAGE_SIZE,**({"starting_after":after} if after else {})})
            require(page.get("object")=="list" and type(page.get("has_more")) is bool
                    and isinstance(page.get("data"),list) and len(page["data"])<=PAGE_SIZE)
            for value in page["data"]:
                require(isinstance(value,dict) and (value.get("livemode") is False or
                        (prefix=="re_" and "livemode" not in value)))
                key=object_id(value.get("id"),prefix)
                require(key not in seen and object_id(value.get("payment_intent"),"pi_")==intent)
                seen.add(key)
                rows.append(value)
            if not page["has_more"]:
                return rows
            require(bool(page["data"]))
            after=rows[-1]["id"]
        raise ReadFailure("stripe_pagination_budget")

    def reversals(self,payment):
        intent=payment["payment_intent_id"]
        charges=self.pages("/v1/charges",{"payment_intent":intent},"ch_",intent)
        refunds=self.pages("/v1/refunds",{"payment_intent":intent},"re_",intent)
        disputes=self.pages("/v1/disputes",{"payment_intent":intent},"du_",intent)
        charge_ids={charge["id"] for charge in charges}
        if payment["latest_charge"] is not None:
            if payment["latest_charge"] not in charge_ids:
                raise ReadFailure("stripe_charge_coverage")
        for charge in charges:
            require(type(charge.get("amount_refunded")) is int and charge["amount_refunded"]>=0
                    and type(charge.get("refunded")) is bool and type(charge.get("disputed")) is bool)
        refund_rows=[]
        dispute_rows=[]
        for value in refunds:
            require(object_id(value.get("charge"),"ch_") in charge_ids and value.get("status") in
                    {"pending","requires_action","succeeded","failed","canceled"}
                    and type(value.get("amount")) is int and value["amount"]>=0)
            refund_rows.append({"id":value["id"],"charge":object_id(value["charge"],"ch_"),"status":value["status"],"amount_minor":value["amount"]})
        for value in disputes:
            require(object_id(value.get("charge"),"ch_") in charge_ids and value.get("status") in
                    {"warning_needs_response","warning_under_review","warning_closed","needs_response","under_review","won","lost","prevented"})
            dispute_rows.append({"id":value["id"],"charge":object_id(value["charge"],"ch_"),"status":value["status"]})
        # Contradictions can be eventual consistency or a reversal arriving mid-read: retry.
        for charge in charges:
            history=[row for row in refund_rows if row["charge"]==charge["id"]]
            succeeded=sum(row["amount_minor"] for row in history if row["status"]=="succeeded")
            # Pending refunds can affect charge totals before their final status arrives.
            covered=sum(row["amount_minor"] for row in history)
            if not succeeded<=charge["amount_refunded"]<=covered or ((charge["refunded"] or charge["amount_refunded"]>0) and not history) or (charge["disputed"] and not any(row["charge"]==charge["id"] for row in dispute_rows)):
                raise ReadFailure("stripe_reversal_changed")
        current=self.get("/v1/payment_intents/"+intent)
        require(current.get("livemode") is False and current.get("id")==intent)
        if current.get("latest_charge")!=payment["latest_charge"] or current.get("status")!=payment["status"]:
            raise ReadFailure("stripe_payment_changed")
        return refund_rows,dispute_rows
