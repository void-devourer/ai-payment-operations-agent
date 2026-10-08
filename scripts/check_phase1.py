"""Real PostgreSQL and HTTP acceptance checks for the running local Compose stack."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
import time
import unittest
import uuid

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.contracts import Grant
from backend.app.database import Database
from backend.app.reference import grant_access


def local_environment():
    return dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if line and not line.startswith("#"))


class Phase1IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = local_environment()
        cls.console = httpx.Client(base_url="http://127.0.0.1:8000", timeout=10, trust_env=False)
        cls.reference = httpx.Client(base_url="http://127.0.0.1:8001", timeout=10, trust_env=False)
        cls.simulator = httpx.Client(base_url="http://127.0.0.1:8002", timeout=10, trust_env=False)
        cls.runtime_url = f"postgresql://reference_runtime:{cls.env['REFERENCE_DB_PASSWORD']}@127.0.0.1:{cls.env.get('POSTGRES_PORT', '15432')}/reference"
        cls.database = Database(cls.runtime_url)
        for client in (cls.console, cls.reference, cls.simulator):
            response = client.get("/health/ready")
            if response.status_code != 200:
                raise RuntimeError("Compose services are not ready")

    @classmethod
    def tearDownClass(cls):
        cls.database.close()
        for client in (cls.console, cls.reference, cls.simulator):
            client.close()

    def headers(self, purpose, letter="A"):
        return {"Authorization": f"Bearer {self.env[f'WORKSPACE_{letter}_{purpose}_KEY']}"}

    def checkout(self, fault="pause_fulfillment", letter="A"):
        suffix = uuid.uuid4().hex[:16]
        body = {"purchase_id": f"p_{suffix}", "customer_id": f"c_{suffix}", "fault_mode": fault}
        response = self.reference.post("/demo/checkouts", json=body, headers=self.headers("CHECKOUT", letter))
        self.assertEqual(response.status_code, 200, response.text)
        return body, response.json()

    def grant(self, body, **changes):
        return dict(operation_id=f"op_{uuid.uuid4().hex}", workspace_id="ws_a", purchase_id=body["purchase_id"], customer_id=body["customer_id"], product_id="digital_pass", expected_revision=0, proposal_id="test_proposal", expires_at=(datetime.now(UTC) + timedelta(minutes=10)).isoformat()) | changes

    def test_normal_checkout_payment_and_fulfillment(self):
        body, payment = self.checkout("none")
        response = self.reference.post(f"/demo/checkouts/{body['purchase_id']}/pay", headers=self.headers("CHECKOUT"))
        self.assertEqual(response.status_code, 200)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            access = self.reference.get(f"/internal/access/{body['purchase_id']}", headers=self.headers("ADAPTER")).json()
            if access["status"] == "active":
                break
            time.sleep(0.5)
        self.assertEqual(access["status"], "active")
        self.assertEqual(access["revision"], 1)
        from backend.app.detection.policy import (
            AccessBinding, AccessEvidence, AccessStatus, Environment, EvidenceWindow,
            Outcome, PaymentEvidence, PaymentStatus, ProviderScope, Purchase, evaluate_access,
        )
        observed = datetime.now(UTC)
        facts = self.simulator.get(f"/internal/payments/{payment['payment_intent_id']}", headers=self.headers("PROVIDER")).json()
        window = EvidenceWindow(observed, datetime.now(UTC), True)
        binding = AccessBinding("ws_a", body["purchase_id"], body["customer_id"], "digital_pass")
        scope = ProviderScope("ws_a", "sim_ws_a", facts["account_id"], Environment.SIMULATED)
        purchase = Purchase(binding, scope, body["customer_id"], (payment["payment_intent_id"],), 2500, "usd")
        evidence = PaymentEvidence(scope, payment["payment_intent_id"], body["customer_id"], PaymentStatus.SUCCEEDED, facts["amount_received_minor"], facts["currency"], (payment["payment_intent_id"],), facts["refund_count"], facts["dispute_count"], window, window, datetime.fromisoformat(facts["succeeded_at"]))
        target = AccessEvidence(binding, AccessStatus.ACTIVE, access["revision"], access["ever_activated"], window)
        self.assertEqual(evaluate_access(purchase, evidence, target, now=datetime.now(UTC)).outcome, Outcome.HEALTHY)
        owner = httpx.Client(base_url=str(self.console.base_url), trust_env=False)
        try:
            login = owner.post("/dev/sessions/owner_a", headers={"X-Demo-Login-Key": self.env["DEMO_LOGIN_KEY"]})
            self.assertEqual(login.status_code, 200)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                rows = owner.get("/api/workspaces/ws_a/purchases").json()
                if any(row["payload"]["purchase_id"] == body["purchase_id"] for row in rows):
                    break
                time.sleep(0.5)
            self.assertTrue(any(row["payload"]["purchase_id"] == body["purchase_id"] for row in rows))
        finally:
            owner.close()

    def test_receipt_replay_concurrency_changed_payload_and_revision(self):
        body, _ = self.checkout()
        payload = self.grant(body)
        def execute(_):
            return self.reference.post("/internal/access-grants", json=payload, headers=self.headers("ADAPTER"))
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(execute, range(4)))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        receipt = responses[0].json()
        self.assertTrue(all(response.json() == receipt for response in responses))
        changed = self.reference.post("/internal/access-grants", json=payload | {"expected_revision": 1}, headers=self.headers("ADAPTER"))
        self.assertEqual(changed.status_code, 409)
        lookup = self.reference.get(f"/internal/operations/{payload['operation_id']}", headers=self.headers("ADAPTER"))
        self.assertEqual(lookup.json(), receipt)
        different = self.reference.post("/internal/access-grants", json=self.grant(body), headers=self.headers("ADAPTER"))
        self.assertEqual(different.status_code, 409)
        access = self.reference.get(f"/internal/access/{body['purchase_id']}", headers=self.headers("ADAPTER"))
        self.assertEqual(access.json()["revision"], 1)

    def test_failed_precondition_retains_operation_identity(self):
        body, _ = self.checkout()
        payload = self.grant(body, expected_revision=10)
        first = self.reference.post("/internal/access-grants", json=payload, headers=self.headers("ADAPTER"))
        self.assertEqual(first.status_code, 409)
        changed = self.reference.post("/internal/access-grants", json=payload | {"expected_revision": 0}, headers=self.headers("ADAPTER"))
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(self.reference.get(f"/internal/access/{body['purchase_id']}", headers=self.headers("ADAPTER")).json()["revision"], 0)

    def test_access_and_receipt_rollback_together(self):
        body, _ = self.checkout()
        payload = Grant.model_validate(self.grant(body))
        database = self.database
        class FailBeforeReceipt:
            @contextmanager
            def transaction(self, workspace):
                with database.transaction(workspace) as cursor:
                    class Cursor:
                        def execute(self, statement, parameters=None):
                            if statement.startswith("INSERT INTO operation_receipts"):
                                raise RuntimeError("Injected failure after access update")
                            return cursor.execute(statement, parameters)
                        def fetchone(self):
                            return cursor.fetchone()
                    yield Cursor()
        with self.assertRaises(RuntimeError):
            grant_access(FailBeforeReceipt(), "ws_a", payload)
        access = self.reference.get(f"/internal/access/{body['purchase_id']}", headers=self.headers("ADAPTER")).json()
        self.assertEqual((access["status"], access["revision"]), ("inactive", 0))
        receipt = self.reference.get(f"/internal/operations/{payload.operation_id}", headers=self.headers("ADAPTER"))
        self.assertEqual(receipt.status_code, 404)

    def test_tenant_isolation_and_pool_context_reset(self):
        body, _ = self.checkout()
        response = self.reference.get(f"/internal/access/{body['purchase_id']}", headers=self.headers("ADAPTER", "B"))
        self.assertEqual(response.status_code, 404)
        with self.database.transaction("ws_a") as cursor:
            cursor.execute("SELECT count(*) AS count FROM access_grants WHERE purchase_id=%s", (body["purchase_id"],))
            self.assertEqual(cursor.fetchone()["count"], 1)
        with self.database.transaction() as cursor:
            cursor.execute("SELECT count(*) AS count FROM access_grants")
            self.assertEqual(cursor.fetchone()["count"], 0)
            cursor.execute("SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            role = cursor.fetchone()
            self.assertFalse(role["rolsuper"] or role["rolbypassrls"])
            cursor.execute("SELECT has_database_privilege(current_user,'console','CONNECT') AS allowed")
            self.assertFalse(cursor.fetchone()["allowed"])
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            with self.database.transaction("ws_a") as cursor:
                cursor.execute("UPDATE operation_receipts SET receipt='{}'::jsonb")

    def test_sessions_membership_csrf_and_service_purpose(self):
        with httpx.Client(base_url=str(self.console.base_url), trust_env=False) as client:
            self.assertEqual(client.get("/api/workspaces/ws_a/purchases").status_code, 401)
            login = client.post("/dev/sessions/owner_a", headers={"X-Demo-Login-Key": self.env["DEMO_LOGIN_KEY"]})
            self.assertEqual(login.status_code, 200)
            self.assertEqual(client.get("/api/workspaces/ws_b/purchases").status_code, 403)
            self.assertEqual(client.post("/api/workspaces/ws_a/sessions/revoke").status_code, 403)
            csrf = login.json()["csrf_token"]
            self.assertEqual(client.post("/api/workspaces/ws_a/sessions/revoke", headers={"X-CSRF-Token": csrf}).status_code, 204)
            self.assertEqual(client.get("/api/workspaces/ws_a/purchases").status_code, 401)
        body, _ = self.checkout()
        response = self.reference.post("/internal/access-grants", json=self.grant(body), headers=self.headers("REGISTRATION"))
        self.assertEqual(response.status_code, 401)

    def test_signed_simulator_event_has_exact_raw_body(self):
        import hashlib
        import hmac
        body, payment = self.checkout()
        self.reference.post(f"/demo/checkouts/{body['purchase_id']}/pay", headers=self.headers("CHECKOUT")).raise_for_status()
        signed = self.simulator.get(f"/internal/events/sim_evt_{payment['payment_intent_id']}/signed", headers=self.headers("PROVIDER"))
        signed.raise_for_status()
        data = signed.json()
        pieces = dict(piece.split("=", 1) for piece in data["signature"].split(","))
        expected = hmac.new(self.env["WORKSPACE_A_WEBHOOK_KEY"].encode(), f"{pieces['t']}.{data['body']}".encode(), hashlib.sha256).hexdigest()
        self.assertTrue(hmac.compare_digest(pieces["v1"], expected))
        self.assertEqual(json.loads(data["body"])["api_version"], "simulator.v1")

    def test_immutable_registration_and_unique_attempt_binding(self):
        suffix = uuid.uuid4().hex[:16]
        purchase = dict(workspace_id="ws_a", purchase_id=f"mapped_{suffix}", customer_id=f"customer_{suffix}", product_id="digital_pass", expected_amount_minor=2500, currency="usd", connection_id="sim_ws_a", provider_customer_id=f"customer_{suffix}")
        for _ in range(2):
            self.assertEqual(self.console.post("/api/purchases", json=purchase, headers=self.headers("REGISTRATION")).status_code, 200)
        self.assertEqual(self.console.post("/api/purchases", json=purchase | {"expected_amount_minor": 2501}, headers=self.headers("REGISTRATION")).status_code, 409)
        other = purchase | {"purchase_id": f"other_{suffix}"}
        self.assertEqual(self.console.post("/api/purchases", json=other, headers=self.headers("REGISTRATION")).status_code, 200)
        attempt = {"payment_intent_id": f"sim_pi_{suffix}"}
        self.assertEqual(self.console.post(f"/api/purchases/{purchase['purchase_id']}/payment-attempts", json=attempt, headers=self.headers("REGISTRATION")).status_code, 200)
        self.assertEqual(self.console.post(f"/api/purchases/{other['purchase_id']}/payment-attempts", json=attempt, headers=self.headers("REGISTRATION")).status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
