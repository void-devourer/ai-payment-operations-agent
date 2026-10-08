"""Phase 1 purchase registry and local-session console API."""

from datetime import UTC, datetime, timedelta
import hmac
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg2.extras import Json

from .contracts import AttemptRegistration, Identifier, PurchaseRegistration
from .database import digest
from .security import actor, service_workspace
from .jobs import enqueue


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
        cursor.execute("INSERT INTO payment_attempts VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING payment_intent_id", (workspace, purchase_id, purchase["connection_id"], body.payment_intent_id))
        inserted = cursor.fetchone() is not None
        cursor.execute("SELECT purchase_id FROM payment_attempts WHERE workspace_id=%s AND connection_id=%s AND payment_intent_id=%s", (workspace, purchase["connection_id"], body.payment_intent_id))
        if cursor.fetchone()["purchase_id"] != purchase_id:
            raise HTTPException(409, "Attempt already bound to another purchase")
        if inserted:
            enqueue(cursor,workspace,purchase["connection_id"],body.payment_intent_id)
            cursor.execute("""UPDATE evidence_heads SET generation=generation+1,observation_id=NULL
                WHERE purchase_id=%s""", (purchase_id,))
    return {"registered": True}


@router.get("/api/workspaces/{workspace}/purchases")
def list_purchases(workspace: str, request: Request):
    subject = actor(request, workspace)
    with request.app.state.database.transaction(workspace, subject) as cursor:
        cursor.execute("SELECT payload, registered_at FROM purchases ORDER BY registered_at DESC, purchase_id LIMIT 100")
        return cursor.fetchall()


@router.get("/api/workspaces/{workspace}/integration-health")
def integration_health(workspace: Identifier, request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("SELECT state,count(*) AS count FROM inbox GROUP BY state")
        receipts=cursor.fetchall()
        cursor.execute("SELECT state,count(*) AS count,min(created_at) AS oldest_created_at FROM jobs GROUP BY state")
        jobs=cursor.fetchall()
        return {"environment":"simulated","api_version":"simulator.v1","receipts":receipts,"jobs":jobs}


@router.get("/api/workspaces/{workspace}/jobs")
def list_jobs(workspace: Identifier, request: Request, after: Identifier | None=None):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT job_id,connection_id,payment_intent_id,state,attempts,due_at,last_error,
            lease_until,created_at,updated_at FROM jobs WHERE job_id>%s ORDER BY job_id LIMIT 51""", (after or "",))
        rows=cursor.fetchall()
        return {"data":rows[:50],"next_cursor":rows[49]["job_id"] if len(rows)>50 else None}


@router.post("/api/workspaces/{workspace}/jobs/{job_id}/redrive")
def redrive(workspace: Identifier, job_id: Identifier, request: Request):
    subject=actor(request,workspace,write=True)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("SELECT state FROM jobs WHERE job_id=%s FOR UPDATE", (job_id,))
        row=cursor.fetchone()
        if row is None:
            raise HTTPException(404,"Job not found")
        if row["state"]!="dead":
            raise HTTPException(409,"Only dead jobs can be redriven")
        cursor.execute("""UPDATE jobs SET state='queued',attempts=0,due_at=now(),lease_token=NULL,
            lease_until=NULL,last_error=NULL,updated_at=now() WHERE job_id=%s""", (job_id,))
        cursor.execute("INSERT INTO job_audit(workspace_id,audit_id,job_id,subject,action) VALUES (%s,%s,%s,%s,'redrive')",
                       (workspace,uuid.uuid4().hex,job_id,subject))
    return {"job_id":job_id,"state":"queued"}


@router.get("/api/workspaces/{workspace}/purchases/{purchase_id}/evidence")
def latest_evidence(workspace: Identifier,purchase_id: Identifier,request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT o.* FROM evidence_heads h JOIN observations o
            ON o.workspace_id=h.workspace_id AND o.observation_id=h.observation_id
            WHERE h.purchase_id=%s AND o.generation=h.generation""", (purchase_id,))
        row=cursor.fetchone()
        if row is None:
            raise HTTPException(404,"No verified observation available")
        return row


@router.get("/api/workspaces/{workspace}/receipts")
def list_receipts(workspace: Identifier,request: Request,after: Identifier | None=None):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT event_id,event_type,api_version,state,body_digest,received_at,source FROM inbox
            WHERE event_id>%s ORDER BY event_id LIMIT 51""", (after or "",))
        rows=cursor.fetchall()
        return {"data":rows[:50],"next_cursor":rows[49]["event_id"] if len(rows)>50 else None}
