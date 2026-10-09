"""Release security and isolated restore/migration checks; local synthetic data."""
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase4 import Phase4IntegrationTests, WORKERS
from scripts.restore_drill import admin_url, create_scratch, drill
from scripts.migrate import migrate
from backend.app.repairs import claim_repair


class ReleaseTests(unittest.TestCase):
    setUpClass = classmethod(Phase4IntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(Phase4IntegrationTests.tearDownClass.__func__)
    headers = Phase4IntegrationTests.headers
    purchase = Phase4IntegrationTests.purchase
    lease = Phase4IntegrationTests.lease
    overdue = Phase4IntegrationTests.overdue
    refresh = Phase4IntegrationTests.refresh
    admin = Phase4IntegrationTests.admin
    cases = Phase4IntegrationTests.cases
    login = Phase4IntegrationTests.login
    fixture = Phase4IntegrationTests.fixture
    operation = Phase4IntegrationTests.operation
    lease_operation = Phase4IntegrationTests.lease_operation
    execute = Phase4IntegrationTests.execute
    access = Phase4IntegrationTests.access
    base = Phase4IntegrationTests.base

    def test_01_read_endpoint_authorization_matrix(self):
        paths = ['/purchases', '/integration-health', '/jobs', '/receipts', '/cases',
                 '/reconciliation', '/purchases/missing/evidence', '/cases/missing',
                 '/cases/missing/repairs', '/purchases/missing/timeline']
        self.http.cookies.clear()
        for path in paths:
            with self.subTest(identity='anonymous', path=path):
                self.assertEqual(self.http.get(self.base + path).status_code, 401)
        self.login('owner_b')
        for path in paths:
            with self.subTest(identity='other_workspace', path=path):
                self.assertEqual(self.http.get(self.base + path).status_code, 403)
        self.login('viewer_a')
        for path in paths[:6]:
            self.assertEqual(self.http.get(self.base + path).status_code, 200)

    def test_06_mutating_endpoint_role_and_csrf_matrix(self):
        evidence = {'reason': 'Reviewed synthetic fixture', 'observation_id': 'missing', 'fingerprint': 'a' * 64}
        actions = [('/jobs/missing/redrive', None), ('/cases/missing/dismiss', evidence),
                   ('/cases/missing/proposals', evidence),
                   ('/proposals/missing/decisions', {'decision': 'approve', 'reason': 'Reviewed fixture', 'payload_digest': 'a' * 64}),
                   ('/operations/missing/recover', None)]
        self.http.cookies.clear()
        for path, body in actions:
            self.assertEqual(self.http.post(self.base + path, json=body).status_code, 401)
        csrf = self.login('viewer_a')
        for path, body in actions:
            self.assertEqual(self.http.post(self.base + path, json=body, headers=csrf).status_code, 403)
        csrf = self.login('owner_b')
        for path, body in actions:
            self.assertEqual(self.http.post(self.base + path, json=body, headers=csrf).status_code, 403)
        self.login('owner_a')
        for path, body in actions:
            self.assertEqual(self.http.post(self.base + path, json=body).status_code, 403)

    def test_02_new_repairs_pause_without_losing_queued_work(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        self.admin('console', 'UPDATE execution_control SET enabled=false', ())
        try:
            # A manually held lease cannot bypass the dispatch check either.
            before = self.access(body)
            self.execute(proposal)
            after = self.access(body)
            self.assertEqual(after['revision'], before['revision'])
            self.assertEqual(after['status'], 'inactive')
            operation = self.operation(proposal['payload']['operation_id'])
            self.assertIsNone(operation['dispatch_started_at'])
            self.assertEqual(operation['last_error'], 'execution_paused')
            claimed = claim_repair(self.database, 'ws_a')
            self.assertTrue(claimed is None or claimed['dispatch_started_at'] is not None)
            _, _, _, pending, csrf, decision = self.fixture(False)
            response = self.http.post(self.base + '/proposals/' + pending['proposal_id'] + '/decisions', json=decision, headers=csrf)
            self.assertEqual(response.status_code, 503)
        finally:
            self.admin('console', 'UPDATE execution_control SET enabled=true', ())

    def test_03_runtime_cannot_change_execution_or_audit_records(self):
        with self.database.transaction('ws_a') as cursor:
            for table in ['execution_control', 'repair_approvals', 'repair_attempts', 'case_audit', 'job_audit']:
                cursor.execute("SELECT has_table_privilege(current_user,%s,'UPDATE') AS u,has_table_privilege(current_user,%s,'DELETE') AS d", (table, table))
                row = cursor.fetchone()
                self.assertFalse(row['u'])
                self.assertFalse(row['d'])

    def test_04_backup_preserves_pending_identity_and_disables_execution(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        result = drill()
        with psycopg2.connect(admin_url(self.env, result['scratch_database'])) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute('SELECT * FROM repair_operations WHERE operation_id=%s', (proposal['payload']['operation_id'],))
                row = cursor.fetchone()
                self.assertEqual(row['state'], 'queued')
                self.assertEqual(row['proposal_id'], proposal['proposal_id'])
                self.assertIsNone(row['dispatch_started_at'])
                cursor.execute('SELECT enabled FROM execution_control')
                self.assertFalse(cursor.fetchone()['enabled'])
                cursor.execute('SELECT count(*) AS n FROM sessions')
                self.assertEqual(cursor.fetchone()['n'], 0)

    def test_05_previous_schema_upgrade_and_checksum_rejection(self):
        scratch = create_scratch(self.env)
        url = admin_url(self.env, scratch)
        with psycopg2.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE schema_migrations(version text PRIMARY KEY,digest text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())')
                for path in sorted((ROOT / 'infra/migrations/console').glob('*.sql')):
                    if path.name.startswith('006_'):
                        break
                    statement = path.read_text(encoding='utf-8')
                    cursor.execute(statement)
                    cursor.execute('INSERT INTO schema_migrations(version,digest) VALUES (%s,%s)', (path.name, hashlib.sha256(statement.encode()).hexdigest()))
        migrate('console', url)
        migrate('console', url)
        with psycopg2.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM schema_migrations')
                self.assertEqual(cursor.fetchone()[0], 6)
                cursor.execute("UPDATE schema_migrations SET digest='tampered' WHERE version='001_foundation.sql'")
        with self.assertRaises(ValueError):
            migrate('console', url)

    def test_07_paused_execution_still_recovers_known_dispatch_receipt(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        payload = proposal['payload']
        self.http.post('http://127.0.0.1:8001/internal/access-grants',
                       headers=self.headers('ADAPTER'), json=payload).raise_for_status()
        self.admin('console', "UPDATE repair_operations SET dispatch_started_at=now(),state='outcome_unknown' WHERE operation_id=%s", (payload['operation_id'],))
        self.admin('console', 'UPDATE execution_control SET enabled=false', ())
        try:
            result = self.execute(proposal)
            self.assertEqual(result['state'], 'succeeded')
            self.assertEqual(result['receipt']['operation_id'], payload['operation_id'])
            self.assertEqual(self.access(body)['revision'], 1)
        finally:
            self.admin('console', 'UPDATE execution_control SET enabled=true', ())

    def test_08_canary_absent_from_validation_responses_and_service_logs(self):
        canary = 'sk_live_CANARY_' + uuid.uuid4().hex
        for port, path in [(8000, '/api/purchases'), (8001, '/demo/checkouts'), (8002, '/internal/payments')]:
            response = self.http.post(f'http://127.0.0.1:{port}' + path, json={canary: canary})
            self.assertEqual(response.status_code, 422)
            self.assertTrue(canary not in response.text, 'Validation leaked submitted canary')
            self.http.get(f'http://127.0.0.1:{port}/health/live', params={'secret_canary': canary}).raise_for_status()
        logs = subprocess.run(['docker', 'compose', 'logs', '--since', '1m', 'console', 'reference', 'simulator'],
                              cwd=ROOT, capture_output=True, check=True)
        self.assertTrue(canary.encode() not in logs.stdout + logs.stderr, 'Service logs leaked submitted canary')


if __name__ == '__main__':
    try:
        subprocess.run(['docker', 'compose', 'stop', *WORKERS], cwd=ROOT, capture_output=True, check=True)
        unittest.main(defaultTest='ReleaseTests', verbosity=2)
    finally:
        subprocess.run(['docker', 'compose', 'start', *WORKERS], cwd=ROOT, capture_output=True, check=True)
