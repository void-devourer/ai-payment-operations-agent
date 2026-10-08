"""Independent persistent synthetic provider; never connects to Stripe."""

from datetime import UTC, datetime
import hashlib
import hmac
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import Json
from pydantic import Field
from typing import Literal

from .contracts import Contract, Identifier, SimulatedPayment
from .security import service_workspace


router = APIRouter()


def intent_id(workspace: str, purchase: str) -> str:
    return "sim_pi_" + hashlib.sha256(f"{workspace}:{purchase}".encode()).hexdigest()[:32]


@router.post("/internal/payments")
def create_payment(body: SimulatedPayment, request: Request):
    workspace = service_workspace(request, "provider")
    identifier = intent_id(workspace, body.purchase_id if body.attempt_id is None else f"{body.purchase_id}:{body.attempt_id}")
    payload = body.model_dump(mode="json",exclude_none=True)
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("INSERT INTO payments(workspace_id,payment_intent_id,payload) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (workspace, identifier, Json(payload)))
        cursor.execute("SELECT payload FROM payments WHERE workspace_id=%s AND payment_intent_id=%s", (workspace, identifier))
        if cursor.fetchone()["payload"] != payload:
            raise HTTPException(409, "Payment creation payload conflict")
    return {"payment_intent_id": identifier, "simulated": True}


@router.get("/internal/payments/{identifier}")
def get_payment(identifier: Identifier, request: Request):
    workspace = service_workspace(request, "provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM payments WHERE workspace_id=%s AND payment_intent_id=%s", (workspace, identifier))
        payment = cursor.fetchone()
        if payment is None:
            raise HTTPException(404, "Payment not found")
        if payment["read_fault"]:
            raise HTTPException(payment["read_fault"],"Controlled simulator read fault",headers={"Retry-After":"2"})
        cursor.execute("SELECT kind,count(*) AS count FROM reversals WHERE payment_intent_id=%s GROUP BY kind", (identifier,))
        counts={row["kind"]:row["count"] for row in cursor.fetchall()}
        return {"payment_intent_id": identifier, "workspace_id": workspace, "account_id": f"sim_acct_{workspace}", "environment": "simulated", "api_version":"simulator.v1", "purchase_id":payment["payload"]["purchase_id"], "status": payment["status"], "amount_received_minor": payment["payload"]["amount_minor"] if payment["status"] == "succeeded" else 0, "currency": payment["payload"]["currency"], "customer_id": payment["payload"]["customer_id"], "refund_count": counts.get("refunds",0), "dispute_count": counts.get("disputes",0), "reversal_generation":payment["reversal_generation"], "succeeded_at": payment["succeeded_at"], "complete": True}


@router.post("/internal/payments/{identifier}/confirm")
def confirm_payment(identifier: Identifier, request: Request):
    workspace = service_workspace(request, "provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM payments WHERE workspace_id=%s AND payment_intent_id=%s FOR UPDATE", (workspace, identifier))
        payment = cursor.fetchone()
        if payment is None:
            raise HTTPException(404, "Payment not found")
        if payment["status"] != "succeeded":
            cursor.execute("UPDATE payments SET status='succeeded',succeeded_at=now() WHERE workspace_id=%s AND payment_intent_id=%s", (workspace, identifier))
            event = {"id": f"sim_evt_{identifier}", "object": "event", "api_version": "simulator.v1", "type": "payment_intent.succeeded", "livemode": False, "created": int(time.time()), "account": f"sim_acct_{workspace}", "data": {"object": {"id": identifier, "status": "succeeded", "amount_received": payment["payload"]["amount_minor"], "currency": payment["payload"]["currency"], "metadata": {"purchase_id": payment["payload"]["purchase_id"]}}}}
            cursor.execute("INSERT INTO events(workspace_id,event_id,payload) VALUES (%s,%s,%s)", (workspace, event["id"], Json(event)))
    return {"status": "succeeded", "simulated": True}


@router.get("/internal/events/{identifier}/signed")
def signed_event(identifier: Identifier, request: Request):
    workspace = service_workspace(request, "provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT payload FROM events WHERE workspace_id=%s AND event_id=%s", (workspace, identifier))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, "Event not found")
    body = json.dumps(row["payload"], sort_keys=True, separators=(",", ":"))
    timestamp = int(datetime.now(UTC).timestamp())
    key = request.app.state.settings.keys[workspace]["webhook"].encode()
    signature = hmac.new(key, f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return {"body": body, "signature": f"t={timestamp},v1={signature}", "simulated": True}


@router.get("/internal/payments/{identifier}/{kind}")
def list_reversals(identifier: Identifier,kind: Literal['refunds','disputes'],request: Request,
                   limit: int=20,starting_after: Identifier | None=None):
    if not 1<=limit<=20:
        raise HTTPException(422,"Page limit must be 1..20")
    workspace=service_workspace(request,"provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT reversal_generation,read_fault,page_fault FROM payments WHERE payment_intent_id=%s", (identifier,))
        payment=cursor.fetchone()
        if payment is None:
            raise HTTPException(404,"Payment not found")
        if payment["read_fault"] or (starting_after and payment["page_fault"]):
            raise HTTPException(payment["read_fault"] or 503,"Controlled simulator page fault",headers={"Retry-After":"2"})
        cursor.execute("""SELECT resource_id AS id,status,amount_minor,payment_intent_id FROM reversals
            WHERE payment_intent_id=%s AND kind=%s AND resource_id>%s ORDER BY resource_id LIMIT %s""",
            (identifier,kind,starting_after or "",limit+1))
        rows=cursor.fetchall()
    return {"data":rows[:limit],"has_more":len(rows)>limit,"payment_intent_id":identifier,
            "reversal_generation":payment["reversal_generation"],"api_version":"simulator.v1","complete":True}


class Scenario(Contract):
    status: Literal['processing','requires_capture','failed','canceled','succeeded'] | None=None
    read_fault: Literal[0,403,429,503]=0
    page_fault: bool=False


@router.post("/internal/payments/{identifier}/scenario")
def scenario(identifier: Identifier,body: Scenario,request: Request):
    workspace=service_workspace(request,"provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("UPDATE payments SET status=coalesce(%s,status),read_fault=%s,page_fault=%s WHERE payment_intent_id=%s RETURNING payload,status",
                       (body.status,body.read_fault,body.page_fault,identifier))
        payment=cursor.fetchone()
        if payment is None:
            raise HTTPException(404,"Payment not found")
        event_type={"failed":"payment_intent.payment_failed"}.get(payment["status"],"payment_intent."+payment["status"])
        emit(cursor,workspace,identifier,event_type,{"id":identifier,"status":payment["status"]})
    return {"simulated":True}


class Reversal(Contract):
    resource_id: Identifier
    status: Literal['pending','succeeded','failed','won','lost','under_review']
    amount_minor: int=Field(strict=True,ge=0,le=10**12)


def emit(cursor,workspace,intent,event_type,resource):
    event={"id":"sim_evt_"+uuid.uuid4().hex,"object":"event","api_version":"simulator.v1",
           "type":event_type,"livemode":False,"created":int(time.time()),"account":f"sim_acct_{workspace}","data":{"object":resource}}
    cursor.execute("INSERT INTO events(workspace_id,event_id,payload) VALUES (%s,%s,%s)", (workspace,event["id"],Json(event)))


@router.post("/internal/payments/{identifier}/{kind}")
def add_reversal(identifier: Identifier,kind: Literal['refunds','disputes'],body: Reversal,request: Request):
    workspace=service_workspace(request,"provider")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT payload FROM payments WHERE payment_intent_id=%s FOR UPDATE", (identifier,))
        payment=cursor.fetchone()
        if payment is None:
            raise HTTPException(404,"Payment not found")
        if body.amount_minor>payment["payload"]["amount_minor"]:
            raise HTTPException(422,"Reversal exceeds payment")
        cursor.execute("""INSERT INTO reversals VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING resource_id""",
                       (workspace,identifier,kind,body.resource_id,body.status,body.amount_minor))
        inserted=cursor.fetchone() is not None
        cursor.execute("SELECT status,amount_minor FROM reversals WHERE payment_intent_id=%s AND kind=%s AND resource_id=%s", (identifier,kind,body.resource_id))
        if dict(cursor.fetchone())!={"status":body.status,"amount_minor":body.amount_minor}:
            raise HTTPException(409,"Reversal identity conflict")
        if inserted:
            cursor.execute("UPDATE payments SET reversal_generation=reversal_generation+1 WHERE payment_intent_id=%s", (identifier,))
            emit(cursor,workspace,identifier,"charge.refunded" if kind=="refunds" else "charge.dispute.created",
                 {"id":body.resource_id,"payment_intent":identifier,"status":body.status})
    return {"simulated":True,"registered":True}
