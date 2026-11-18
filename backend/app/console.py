"""Phase 1 purchase registry and local-session console API."""

from datetime import UTC, datetime, timedelta
import hmac
import secrets
import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from psycopg2.extras import Json

from .contracts import AttemptRegistration, Identifier, PurchaseRegistration
from .database import digest
from .security import actor, service_workspace, csrf_token
from .jobs import enqueue


router = APIRouter()
DEMO_SUBJECTS = {"owner_a", "operator_a", "viewer_a", "owner_b"}


@router.post("/dev/sessions/{subject}")
def login(subject: str, request: Request, response: Response):
    supplied = request.headers.get("X-Demo-Login-Key", "")
    settings = request.app.state.settings
    if subject not in DEMO_SUBJECTS or not hmac.compare_digest(digest(supplied), digest(settings.demo_login_key)):
        raise HTTPException(401, "Incorrect credentials")
    token = secrets.token_urlsafe(32)
    csrf = csrf_token(request, token)
    expires = datetime.now(UTC) + timedelta(seconds=settings.session_seconds)
    with request.app.state.database.transaction() as cursor:
        cursor.execute("INSERT INTO sessions(token_digest,subject,csrf_digest,expires_at) VALUES (%s,%s,%s,%s)", (digest(token), subject, digest(csrf), expires))
    response.set_cookie("payment_session", token, httponly=True, samesite="strict", max_age=settings.session_seconds)
    response.headers["Cache-Control"] = "no-store"
    return {"subject": subject, "csrf_token": csrf, "expires_at": expires,
            "confirmation_until": datetime.now(UTC) + timedelta(minutes=30)}


@router.get('/api/session')
def restore_session(request: Request, response: Response):
    token = request.cookies.get('payment_session', '')
    if not token or len(token) > 128:
        raise HTTPException(401, 'Session required')
    csrf = csrf_token(request, token)
    expires = datetime.now(UTC) + timedelta(seconds=request.app.state.settings.session_seconds)
    with request.app.state.database.transaction() as cursor:
        # Returning sessions renew their idle lease; revoked/expired sessions cannot return.
        cursor.execute('''UPDATE sessions SET expires_at=%s,csrf_digest=%s
            WHERE token_digest=%s AND expires_at>now() RETURNING subject,authenticated_at''',
            (expires, digest(csrf), digest(token)))
        session = cursor.fetchone()
        if session is None:
            raise HTTPException(401, 'Session expired or revoked')
    response.set_cookie('payment_session', token, httponly=True, samesite='strict',
                        max_age=request.app.state.settings.session_seconds)
    response.headers['Cache-Control'] = 'no-store'
    return {'subject': session['subject'], 'csrf_token': csrf, 'expires_at': expires,
            'confirmation_until': session['authenticated_at'] + timedelta(minutes=30)}


@router.post('/api/workspaces/{workspace}/sessions/confirm')
def confirm_session(workspace: Identifier, request: Request):
    subject = actor(request, workspace, write=True)
    supplied = request.headers.get('X-Demo-Login-Key', '')
    if not hmac.compare_digest(digest(supplied), digest(request.app.state.settings.demo_login_key)):
        raise HTTPException(401, 'Incorrect credentials')
    with request.app.state.database.transaction() as cursor:
        cursor.execute('''UPDATE sessions SET authenticated_at=now() WHERE token_digest=%s
            AND expires_at>now() RETURNING authenticated_at''', (digest(request.cookies['payment_session']),))
        session = cursor.fetchone()
        if session is None:
            raise HTTPException(401, 'Session expired or revoked')
    return {'subject': subject, 'confirmation_until': session['authenticated_at'] + timedelta(minutes=30)}


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
    allowed_connections={f"sim_{workspace}"}
    if workspace in request.app.state.settings.stripe:
        allowed_connections.add(f"stripe_{workspace}")
    if workspace in request.app.state.settings.paypal:
        allowed_connections.add(f'paypal_{workspace}')
    if body.workspace_id != workspace or body.connection_id not in allowed_connections:
        raise HTTPException(403, "Connection/workspace mismatch")
    if body.connection_id.startswith('paypal_'):
        import re
        if body.currency!='usd' or re.fullmatch(r'[A-Z0-9]{13}',body.provider_customer_id) is None:
            raise HTTPException(422,'PayPal investigations require USD and a sandbox buyer ID')
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
        if purchase['connection_id'].startswith('paypal_'):
            raise HTTPException(409,'Register typed PayPal orders and captures instead')
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
        cursor.execute("SELECT connection_id,account_id,environment,api_version,provider FROM connections ORDER BY connection_id")
        return {"connections":cursor.fetchall(),"receipts":receipts,"jobs":jobs}


@router.get("/api/workspaces/{workspace}/jobs")
def list_jobs(workspace: Identifier, request: Request, after: Identifier | None=None):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT job_id,connection_id,payment_intent_id,purchase_id,state,attempts,due_at,last_error,
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
        cursor.execute("""SELECT event_id,event_type,api_version,state,body_digest,received_at,source,resource_type,resource_id FROM inbox
            WHERE event_id>%s ORDER BY event_id LIMIT 51""", (after or "",))
        rows=cursor.fetchall()
        return {"data":rows[:50],"next_cursor":rows[49]["event_id"] if len(rows)>50 else None}
