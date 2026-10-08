"""Opaque server-side sessions and purpose/workspace-bound service credentials."""

import hmac

from fastapi import HTTPException, Request

from .database import digest


def service_workspace(request: Request, purpose: str) -> str:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or len(authorization) > 256:
        raise HTTPException(401, "Service credential required")
    supplied = digest(authorization[7:])
    for workspace, keys in request.app.state.settings.keys.items():
        if hmac.compare_digest(supplied, digest(keys[purpose])):
            return workspace
    raise HTTPException(401, "Invalid service credential")


def actor(request: Request, workspace: str, write: bool = False) -> str:
    token = request.cookies.get("payment_session", "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Session required")
    database = request.app.state.database
    with database.transaction() as cursor:
        cursor.execute(
            "SELECT subject, csrf_digest FROM sessions WHERE token_digest=%s AND expires_at > now()",
            (digest(token),),
        )
        session = cursor.fetchone()
    if session is None:
        raise HTTPException(401, "Session expired or revoked")
    with database.transaction(workspace, session["subject"]) as cursor:
        cursor.execute("SELECT role FROM memberships WHERE workspace_id=%s AND subject=%s AND active", (workspace, session["subject"]))
        member = cursor.fetchone()
    if member is None:
        raise HTTPException(403, "Workspace membership required")
    if write:
        if member["role"] not in ("owner", "operator"):
            raise HTTPException(403, "Operator role required")
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not hmac.compare_digest(digest(csrf), session["csrf_digest"]):
            raise HTTPException(403, "CSRF token required")
    return session["subject"]
