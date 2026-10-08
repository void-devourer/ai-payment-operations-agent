"""Phase 1 purchase registry and local-session console API."""

from datetime import UTC, datetime, timedelta
import hmac
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg2.extras import Json

from .contracts import AttemptRegistration, Identifier, PurchaseRegistration
from .database import digest
from .security import actor, service_workspace


router = APIRouter()
DEMO_SUBJECTS = {"owner_a", "operator_a", "viewer_a", "owner_b"}


@router.post("/dev/sessions/{subject}")
def login(subject: str, request: Request, response: Response):
    supplied = request.headers.get("X-Demo-Login-Key", "")
    settings = request.app.state.settings
    if subject not in DEMO_SUBJECTS or not hmac.compare_digest(digest(supplied), digest(settings.demo_login_key)):
        raise HTTPException(401, "Invalid local identity")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(seconds=settings.session_seconds)
    with request.app.state.database.transaction() as cursor:
        cursor.execute("INSERT INTO sessions VALUES (%s,%s,%s,%s)", (digest(token), subject, digest(csrf), expires))
    response.set_cookie("payment_session", token, httponly=True, samesite="strict", max_age=settings.session_seconds)
    response.headers["Cache-Control"] = "no-store"
    return {"subject": subject, "csrf_token": csrf, "expires_at": expires}


@router.post("/api/workspaces/{workspace}/sessions/revoke")
def logout(workspace: str, request: Request):
    actor(request, workspace)
    with request.app.state.database.transaction() as cursor:
        cursor.execute("SELECT csrf_digest FROM sessions WHERE token_digest=%s", (digest(request.cookies["payment_session"]),))
        session = cursor.fetchone()
        csrf = request.headers.get("X-CSRF-Token", "")
        if session is None or not csrf or not hmac.compare_digest(digest(csrf), session["csrf_digest"]):
            raise HTTPException(403, "CSRF token required")
        cursor.execute("DELETE FROM sessions WHERE token_digest=%s", (digest(request.cookies["payment_session"]),))
    response = Response(status_code=204)
    response.delete_cookie("payment_session")
    return response


@router.get("/api/workspaces")
def workspaces(request: Request):
    token = request.cookies.get("payment_session", "")
    with request.app.state.database.transaction() as cursor:
        cursor.execute("SELECT subject FROM sessions WHERE token_digest=%s AND expires_at>now()", (digest(token),))
        session = cursor.fetchone()
    if session is None:
        raise HTTPException(401, "Session required")
    with request.app.state.database.transaction(subject=session["subject"]) as cursor:
        cursor.execute("SELECT workspace_id, role FROM memberships WHERE active ORDER BY workspace_id")
        return cursor.fetchall()


@router.post("/api/purchases")
def register_purchase(body: PurchaseRegistration, request: Request):
    workspace = service_workspace(request, "registration")
    if body.workspace_id != workspace or body.connection_id != f"sim_{workspace}":
        raise HTTPException(403, "Connection/workspace mismatch")
    payload = body.model_dump(mode="json")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("INSERT INTO purchases(workspace_id,purchase_id,customer_id,product_id,expected_amount_minor,currency,connection_id,provider_customer_id,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (workspace, body.purchase_id, body.customer_id, body.product_id, body.expected_amount_minor, body.currency, body.connection_id, body.provider_customer_id, Json(payload)))
        cursor.execute("SELECT payload FROM purchases WHERE workspace_id=%s AND purchase_id=%s", (workspace, body.purchase_id))
        if cursor.fetchone()["payload"] != payload:
            raise HTTPException(409, "Immutable purchase conflict")
    return {"purchase_id": body.purchase_id, "registered": True}


@router.post("/api/purchases/{purchase_id}/payment-attempts")
def register_attempt(purchase_id: Identifier, body: AttemptRegistration, request: Request):
    workspace = service_workspace(request, "registration")
    with request.app.state.database.transaction(workspace) as cursor:
        cursor.execute("SELECT connection_id FROM purchases WHERE workspace_id=%s AND purchase_id=%s", (workspace, purchase_id))
        purchase = cursor.fetchone()
        if purchase is None:
            raise HTTPException(409, "Register purchase before its attempt")
        cursor.execute("INSERT INTO payment_attempts VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (workspace, purchase_id, purchase["connection_id"], body.payment_intent_id))
        cursor.execute("SELECT purchase_id FROM payment_attempts WHERE workspace_id=%s AND connection_id=%s AND payment_intent_id=%s", (workspace, purchase["connection_id"], body.payment_intent_id))
        if cursor.fetchone()["purchase_id"] != purchase_id:
            raise HTTPException(409, "Attempt already bound to another purchase")
    return {"registered": True}


@router.get("/api/workspaces/{workspace}/purchases")
def list_purchases(workspace: str, request: Request):
    subject = actor(request, workspace)
    with request.app.state.database.transaction(workspace, subject) as cursor:
        cursor.execute("SELECT payload, registered_at FROM purchases ORDER BY registered_at DESC, purchase_id LIMIT 100")
        return cursor.fetchall()
