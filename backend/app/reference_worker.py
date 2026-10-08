"""Bounded reference-app registration relay and ordinary fulfillment worker."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

import httpx
from psycopg2.extras import Json

from .config import Settings
from .contracts import Grant
from .database import Database
from .reference import CURRENCY, PRICE_MINOR, ensure_provider_payment, grant_access


def relay_once(app, workspace: str) -> bool:
    database, settings = app.state.database, app.state.settings
    lease = str(uuid.uuid4())
    with database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM registration_outbox WHERE due_at<=now() AND (state='pending' OR (state='sending' AND lease_until<now())) AND (kind='purchase' OR EXISTS (SELECT 1 FROM registration_outbox p WHERE p.workspace_id=registration_outbox.workspace_id AND p.purchase_id=registration_outbox.purchase_id AND p.kind='purchase' AND p.state='sent')) ORDER BY due_at,purchase_id,kind LIMIT 1 FOR UPDATE SKIP LOCKED")
        job = cursor.fetchone()
        if job is None:
            return False
        cursor.execute("UPDATE registration_outbox SET state='sending',lease_id=%s,lease_until=now()+interval '30 seconds',attempts=attempts+1 WHERE workspace_id=%s AND purchase_id=%s AND kind=%s", (lease, workspace, job["purchase_id"], job["kind"]))
    path = "/api/purchases" if job["kind"] == "purchase" else f"/api/purchases/{job['purchase_id']}/payment-attempts"
    error, terminal = None, False
    try:
        response = app.state.http.post(settings.console_url + path, json=job["payload"], headers={"Authorization": f"Bearer {settings.keys[workspace]['registration']}"})
        if not 200 <= response.status_code < 300:
            error = f"http_{response.status_code}"
            terminal = response.status_code in (400, 401, 403, 409, 422)
        elif response.json().get("registered") is not True:
            error, terminal = "invalid_registration_acknowledgment", True
    except (httpx.RequestError, ValueError):
        error = "console_unavailable"
    attempts = job["attempts"] + 1
    with database.transaction(workspace) as cursor:
        cursor.execute("UPDATE registration_outbox SET state=%s,last_error=%s,due_at=%s,lease_id=NULL,lease_until=NULL WHERE workspace_id=%s AND purchase_id=%s AND kind=%s AND lease_id=%s AND lease_until>now()", ("sent" if error is None else "dead" if terminal or attempts >= 12 else "pending", error, datetime.now(UTC) + timedelta(seconds=min(60, 2**min(attempts, 6))), workspace, job["purchase_id"], job["kind"], lease))
    return True


def fulfill_once(app, workspace: str, progress=None) -> bool:
    database = app.state.database
    with database.transaction(workspace) as cursor:
        cursor.execute("SELECT * FROM orders WHERE fulfillment_state='pending' AND fault_mode='none' ORDER BY purchase_id LIMIT 20")
        orders = cursor.fetchall()
    progressed = False
    for order in orders:
        if progress is not None:
            progress()
        try:
            headers = ensure_provider_payment(app, workspace, order)
            response = app.state.http.get(app.state.settings.simulator_url + f"/internal/payments/{order['payment_intent_id']}", headers=headers)
            response.raise_for_status()
            facts = response.json()
            if facts.get("status") != "succeeded":
                continue
            if (facts.get("workspace_id") != workspace or facts.get("payment_intent_id") != order["payment_intent_id"] or facts.get("account_id") != f"sim_acct_{workspace}" or facts.get("environment") != "simulated" or facts.get("customer_id") != order["customer_id"] or facts.get("amount_received_minor") != PRICE_MINOR or facts.get("currency") != CURRENCY or facts.get("refund_count") != 0 or facts.get("dispute_count") != 0 or facts.get("complete") is not True):
                raise ValueError("provider_evidence_mismatch")
            with database.transaction(workspace) as cursor:
                cursor.execute("SELECT * FROM orders WHERE workspace_id=%s AND purchase_id=%s FOR UPDATE", (workspace, order["purchase_id"]))
                current = cursor.fetchone()
                if current["fulfillment_state"] != "pending":
                    continue
                if current["fulfillment_payload"] is None:
                    payload = Grant(operation_id=f"normal:{order['purchase_id']}", workspace_id=workspace, purchase_id=order["purchase_id"], customer_id=order["customer_id"], product_id=order["product_id"], expected_revision=0, proposal_id=f"normal:{order['purchase_id']}", expires_at=datetime.now(UTC)+timedelta(minutes=10)).model_dump(mode="json")
                    cursor.execute("UPDATE orders SET fulfillment_payload=%s WHERE workspace_id=%s AND purchase_id=%s", (Json(payload), workspace, order["purchase_id"]))
                else:
                    payload = current["fulfillment_payload"]
            status, receipt = grant_access(database, workspace, Grant.model_validate(payload))
            with database.transaction(workspace) as cursor:
                cursor.execute("SELECT status FROM access_grants WHERE workspace_id=%s AND purchase_id=%s", (workspace, order["purchase_id"]))
                active = cursor.fetchone()["status"] == "active"
                cursor.execute("UPDATE orders SET fulfillment_state=%s,last_error=%s WHERE workspace_id=%s AND purchase_id=%s", ("succeeded" if active else "blocked", None if status == 200 else receipt["result"], workspace, order["purchase_id"]))
            progressed = True
        except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
            with database.transaction(workspace) as cursor:
                cursor.execute("UPDATE orders SET last_error='provider_unavailable_or_invalid' WHERE workspace_id=%s AND purchase_id=%s", (workspace, order["purchase_id"]))
    return progressed


def main():
    heartbeat = Path("/tmp/reference-worker-heartbeat")
    heartbeat.unlink(missing_ok=True)
    settings = Settings.from_env("reference")
    database = Database(settings.database_url)
    with httpx.Client(timeout=5, trust_env=False) as client:
        app = SimpleNamespace(state=SimpleNamespace(settings=settings, database=database, http=client))
        try:
            while True:
                for workspace in settings.keys:
                    heartbeat.touch()
                    relay_once(app, workspace)
                    fulfill_once(app, workspace, progress=heartbeat.touch)
                heartbeat.touch()
                time.sleep(1)
        finally:
            database.close()


if __name__ == "__main__":
    main()
