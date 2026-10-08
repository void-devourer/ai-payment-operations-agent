"""Independent reference business application and atomic access/receipt contract."""

from datetime import UTC, datetime, timedelta
import hashlib
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg2.extras import Json

from .contracts import Checkout, Grant, Identifier, PurchaseRegistration, SimulatedPayment, StripeTestTarget
from .security import service_workspace
from .simulator import intent_id


router = APIRouter()


@router.post("/demo/stripe-targets")
def stripe_test_target(body: StripeTestTarget,request: Request):
    """Development-only inactive target; no provider call or simulator registration."""
    workspace=service_workspace(request,"checkout")
    payload=body.model_dump(mode="json")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",(workspace,body.purchase_id))
        cursor.execute("SELECT payload FROM orders WHERE purchase_id=%s",(body.purchase_id,))
        old=cursor.fetchone()
        if old:
            if old["payload"]!=payload:
                raise HTTPException(409,"Immutable test target conflict")
            return {"created":True,"purchase_id":body.purchase_id}
        cursor.execute("""INSERT INTO orders(workspace_id,purchase_id,customer_id,product_id,payment_intent_id,payload,fault_mode)
            VALUES (%s,%s,%s,'digital_pass',%s,%s,'pause_fulfillment')""",
            (workspace,body.purchase_id,body.customer_id,body.payment_intent_id,Json(payload)))
        cursor.execute("INSERT INTO access_grants(workspace_id,purchase_id,customer_id,product_id) VALUES (%s,%s,%s,'digital_pass')",
                       (workspace,body.purchase_id,body.customer_id))
    return {"created":True,"purchase_id":body.purchase_id}
PRICE_MINOR = 2500
CURRENCY = "usd"


def payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def grant_access(database, workspace: str, grant: Grant):
    if grant.workspace_id != workspace:
        raise HTTPException(403, "Workspace mismatch")
    fingerprint = payload_digest(grant.model_dump(mode="json"))
    with database.transaction(workspace) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))", (workspace, grant.operation_id))
        cursor.execute("SELECT * FROM operation_receipts WHERE workspace_id=%s AND operation_id=%s", (workspace, grant.operation_id))
        previous = cursor.fetchone()
        if previous:
            if previous["payload_digest"] != fingerprint:
                raise HTTPException(409, "Operation payload changed")
            return previous["response_status"], previous["receipt"]
        cursor.execute("SELECT * FROM access_grants WHERE workspace_id=%s AND purchase_id=%s FOR UPDATE", (workspace, grant.purchase_id))
        access = cursor.fetchone()
        if access is None:
            raise HTTPException(404, "Access not found")
        if access["customer_id"] != grant.customer_id or access["product_id"] != grant.product_id:
            raise HTTPException(409, "Access binding mismatch")
        status, reason = 200, "granted"
        if grant.expires_at <= datetime.now(UTC):
            status, reason = 410, "request_expired"
        elif access["revision"] != grant.expected_revision or access["status"] != "inactive" or access["ever_activated"]:
            status, reason = 409, "access_precondition_conflict"
        revision = access["revision"]
        if status == 200:
            cursor.execute("UPDATE access_grants SET status='active',revision=revision+1,ever_activated=true WHERE workspace_id=%s AND purchase_id=%s RETURNING revision", (workspace, grant.purchase_id))
            revision = cursor.fetchone()["revision"]
        receipt = {"operation_id": grant.operation_id, "workspace_id": workspace, "purchase_id": grant.purchase_id, "customer_id": grant.customer_id, "product_id": grant.product_id, "result": reason, "revision": revision, "recorded_at": datetime.now(UTC).isoformat()}
        # Even failed preconditions retain the operation's immutable payload identity.
        cursor.execute("INSERT INTO operation_receipts(workspace_id,operation_id,payload_digest,response_status,receipt) VALUES (%s,%s,%s,%s,%s)", (workspace, grant.operation_id, fingerprint, status, Json(receipt)))
        return status, receipt


@router.post("/demo/checkouts")
def checkout(body: Checkout, request: Request):
    workspace = service_workspace(request, "checkout")
    payload = body.model_dump(mode="json")
    identifier = intent_id(workspace, body.purchase_id)
    registration = PurchaseRegistration(workspace_id=workspace, purchase_id=body.purchase_id, customer_id=body.customer_id, product_id=body.product_id, expected_amount_minor=PRICE_MINOR, currency=CURRENCY, connection_id=f"sim_{workspace}", provider_customer_id=body.customer_id)
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))", (workspace, body.purchase_id))
        cursor.execute("SELECT payload FROM orders WHERE workspace_id=%s AND purchase_id=%s", (workspace, body.purchase_id))
        existing = cursor.fetchone()
        if existing:
            if existing["payload"] != payload:
                raise HTTPException(409, "Checkout payload changed")
            return {"purchase_id": body.purchase_id, "payment_intent_id": identifier, "simulated": True}
        cursor.execute("SELECT purchase_id FROM access_grants WHERE customer_id=%s AND product_id=%s", (body.customer_id, body.product_id))
        if cursor.fetchone():
            raise HTTPException(409, "Customer already has a purchase for this access target")
        cursor.execute("INSERT INTO orders(workspace_id,purchase_id,customer_id,product_id,payment_intent_id,payload,fault_mode) VALUES (%s,%s,%s,%s,%s,%s,%s)", (workspace, body.purchase_id, body.customer_id, body.product_id, identifier, Json(payload), body.fault_mode))
        cursor.execute("INSERT INTO access_grants(workspace_id,purchase_id,customer_id,product_id) VALUES (%s,%s,%s,%s)", (workspace, body.purchase_id, body.customer_id, body.product_id))
        for kind, message in (("purchase", registration.model_dump(mode="json")), ("attempt", {"payment_intent_id": identifier})):
            cursor.execute("INSERT INTO registration_outbox(workspace_id,purchase_id,kind,payload) VALUES (%s,%s,%s,%s)", (workspace, body.purchase_id, kind, Json(message)))
    return {"purchase_id": body.purchase_id, "payment_intent_id": identifier, "amount_minor": PRICE_MINOR, "currency": CURRENCY, "simulated": True}


def ensure_provider_payment(app, workspace: str, order: dict):
    payment = SimulatedPayment(purchase_id=order["purchase_id"], customer_id=order["customer_id"], amount_minor=PRICE_MINOR, currency=CURRENCY)
    settings = app.state.settings
    headers = {"Authorization": f"Bearer {settings.keys[workspace]['provider']}"}
    response = app.state.http.post(settings.simulator_url + "/internal/payments", json=payment.model_dump(mode="json"), headers=headers)
    response.raise_for_status()
    if response.json().get("payment_intent_id") != order["payment_intent_id"]:
        raise ValueError("Simulator returned an unexpected payment binding")
    return headers


@router.post("/demo/checkouts/{purchase_id}/pay")
def pay(purchase_id: Identifier, request: Request):
    workspace = service_workspace(request, "checkout")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM orders WHERE workspace_id=%s AND purchase_id=%s", (workspace, purchase_id))
        order = cursor.fetchone()
    if order is None:
        raise HTTPException(404, "Checkout not found")
    if order["payment_intent_id"].startswith("pi_"):
        raise HTTPException(409,"Stripe test targets are not simulator checkouts")
    headers = ensure_provider_payment(request.app, workspace, order)
    response = request.app.state.http.post(request.app.state.settings.simulator_url + f"/internal/payments/{order['payment_intent_id']}/confirm", headers=headers)
    response.raise_for_status()
    return {"payment_status": "succeeded", "fulfillment_status": "pending", "simulated": True}


@router.get("/internal/access/{purchase_id}")
def read_access(purchase_id: Identifier, request: Request):
    workspace = service_workspace(request, "adapter")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM access_grants WHERE workspace_id=%s AND purchase_id=%s", (workspace, purchase_id))
        access = cursor.fetchone()
    if access is None:
        raise HTTPException(404, "Access not found")
    return dict(access, observed_at=datetime.now(UTC), complete=True)


@router.post("/internal/access-grants")
def grant(body: Grant, request: Request):
    workspace = service_workspace(request, "adapter")
    status, receipt = grant_access(request.app.state.database, workspace, body)
    return JSONResponse(receipt, status_code=status)


@router.get("/internal/operations/{operation_id}")
def operation(operation_id: Identifier, request: Request):
    workspace = service_workspace(request, "adapter")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT receipt FROM operation_receipts WHERE workspace_id=%s AND operation_id=%s", (workspace, operation_id))
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, "Receipt not found; effect absence is not established")
    return row["receipt"]


@router.get("/internal/registration-health")
def registration_health(request: Request):
    workspace = service_workspace(request, "adapter")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT state,count(*) AS count FROM registration_outbox GROUP BY state")
        return {"workspace_id": workspace, "outbox": cursor.fetchall()}


@router.post("/internal/registrations/{purchase_id}/retry")
def retry_registration(purchase_id: Identifier, request: Request):
    workspace = service_workspace(request, "adapter")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("UPDATE registration_outbox SET state='pending',attempts=0,due_at=now(),last_error=NULL WHERE workspace_id=%s AND purchase_id=%s AND state='dead' RETURNING kind", (workspace, purchase_id))
        return {"requeued": [row["kind"] for row in cursor.fetchall()]}
