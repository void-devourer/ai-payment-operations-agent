"""Independent persistent synthetic provider; never connects to Stripe."""

from datetime import UTC, datetime
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import Json

from .contracts import Identifier, SimulatedPayment
from .security import service_workspace


router = APIRouter()


def intent_id(workspace: str, purchase: str) -> str:
    return "sim_pi_" + hashlib.sha256(f"{workspace}:{purchase}".encode()).hexdigest()[:32]


@router.post("/internal/payments")
def create_payment(body: SimulatedPayment, request: Request):
    workspace = service_workspace(request, "provider")
    identifier = intent_id(workspace, body.purchase_id)
    payload = body.model_dump(mode="json")
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
        return {"payment_intent_id": identifier, "workspace_id": workspace, "account_id": f"sim_acct_{workspace}", "environment": "simulated", "status": payment["status"], "amount_received_minor": payment["payload"]["amount_minor"] if payment["status"] == "succeeded" else 0, "currency": payment["payload"]["currency"], "customer_id": payment["payload"]["customer_id"], "refund_count": 0, "dispute_count": 0, "succeeded_at": payment["succeeded_at"], "complete": True}


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
            cursor.execute("INSERT INTO events VALUES (%s,%s,%s)", (workspace, event["id"], Json(event)))
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
