"""Real PostgreSQL/HTTP approval, conditional repair and process-death recovery."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase3 import Phase3IntegrationTests, WORKERS
from backend.app.repairs import claim_repair, decide, execute_repair, propose, ProposalDecision, repair_failed, valid_receipt
from backend.app.cases import Dismissal
from backend.app.jobs import ReadFailure


class Phase4IntegrationTests(unittest.TestCase):
    setUpClass = classmethod(Phase3IntegrationTests.setUpClass.__func__)
    tearDownClass = classmethod(Phase3IntegrationTests.tearDownClass.__func__)
    headers = Phase3IntegrationTests.headers
    purchase = Phase3IntegrationTests.purchase
    lease = Phase3IntegrationTests.lease
    facts = Phase3IntegrationTests.facts
    refresh = Phase3IntegrationTests.refresh
    overdue = Phase3IntegrationTests.overdue
    admin = Phase3IntegrationTests.admin
    cases = Phase3IntegrationTests.cases
    login = Phase3IntegrationTests.login
    grant_independently = Phase3IntegrationTests.grant_independently
    base = 'http://127.0.0.1:8000/api/workspaces/ws_a'

    def fixture(self, approve=True):
        body, intent = self.overdue()
        case = self.cases(body['purchase_id'])[0]
        csrf = self.login()
        response = self.http.post(self.base + f"/cases/{case['case_id']}/proposals", headers=csrf,
            json={'reason': 'Restore the purchased access', 'observation_id': case['latest_observation_id'], 'fingerprint': case['fingerprint']})
        response.raise_for_status()
        proposal = response.json()
        decision = {'decision': 'approve', 'reason': 'Reviewed exact target and evidence', 'payload_digest': proposal['payload_digest']}
        if approve:
            self.http.post(self.base + f"/proposals/{proposal['proposal_id']}/decisions", headers=csrf, json=decision).raise_for_status()
        return body, intent, case, proposal, csrf, decision

    def operation(self, identifier):
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT * FROM repair_operations WHERE operation_id=%s', (identifier,))
            return dict(cursor.fetchone())

    def lease_operation(self, proposal):
        identifier = proposal['payload']['operation_id']
        # Claim only this fixture; normal workers are stopped.
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE repair_operations SET lease_token=%s,lease_until=now()+interval '30 seconds',attempts=attempts+1 WHERE operation_id=%s RETURNING *", (uuid.uuid4().hex, identifier))
            return dict(cursor.fetchone())

    def execute(self, proposal):
        op = self.lease_operation(proposal)
        try:
            execute_repair(self.app, op)
        except ReadFailure as error:
            repair_failed(self.database, op, error)
        return self.operation(op['operation_id'])

    def access(self, body):
        return self.http.get('http://127.0.0.1:8001/internal/access/' + body['purchase_id'], headers=self.headers('ADAPTER')).json()

    def test_01_approval_concurrency_payload_binding_and_verified_recovery(self):
        body, intent, case, proposal, csrf, decision = self.fixture(False)
        url = self.base + f"/proposals/{proposal['proposal_id']}/decisions"
        self.assertEqual(self.http.post(url, headers=csrf, json=decision | {'payload_digest': '0' * 64}).status_code, 409)
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.http.post(url, headers=csrf, json=decision), range(4)))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual(len({r.json()['operation_id'] for r in responses}), 1)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS n FROM repair_operations WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertEqual(cursor.fetchone()['n'], 1)
            cursor.execute('SELECT count(*) AS n FROM repair_approvals WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertEqual(cursor.fetchone()['n'], 1)
        result = self.execute(proposal)
        self.assertEqual(result['state'], 'succeeded')
        self.assertEqual(self.access(body)['revision'], 1)
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'], 'resolved')
        self.assertIsNotNone(result['verification_observation_id'])
        self.assertEqual(self.http.post(url, headers=csrf, json=decision).json()['operation_id'], result['operation_id'])

    def test_02_permission_csrf_cross_workspace_and_rejection(self):
        body, intent, case, proposal, csrf, decision = self.fixture(False)
        url = self.base + f"/proposals/{proposal['proposal_id']}/decisions"
        self.assertEqual(self.http.post(url, json=decision).status_code, 403)
        viewer = self.login('viewer_a')
        self.assertEqual(self.http.post(url, headers=viewer, json=decision).status_code, 403)
        foreign = self.login('owner_b')
        self.assertEqual(self.http.post(url, headers=foreign, json=decision).status_code, 403)
        self.assertEqual(self.http.get(self.base + f"/cases/{case['case_id']}/repairs").status_code, 403)
        csrf = self.login()
        self.http.post(url, headers=csrf, json=decision | {'decision': 'reject'}).raise_for_status()
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT 1 FROM repair_operations WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertIsNone(cursor.fetchone())
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'], 'open')

    def test_03_refund_suspension_and_revision_change_block_dispatch(self):
        for change in ('refund', 'suspended', 'revision'):
            with self.subTest(change=change):
                body, intent, case, proposal, csrf, decision = self.fixture()
                if change == 'refund':
                    self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/refunds', headers=self.headers(),
                        json={'resource_id': 'r_' + uuid.uuid4().hex, 'status': 'pending', 'amount_minor': 1}).raise_for_status()
                else:
                    self.admin('reference', 'UPDATE access_grants SET revision=revision+1,status=%s WHERE purchase_id=%s',
                               ('suspended' if change == 'suspended' else 'inactive', body['purchase_id']))
                result = self.execute(proposal)
                self.assertEqual(result['state'], 'blocked')
                self.assertIsNone(result['dispatch_started_at'])
                self.assertFalse(self.access(body)['ever_activated'])

    def test_04_membership_and_session_revocation_block_dispatch(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        self.admin('console', "UPDATE memberships SET active=false WHERE workspace_id='ws_a' AND subject='owner_a'", ())
        try:
            self.assertEqual(self.execute(proposal)['last_error'], 'approval_authority_revoked')
            self.assertEqual(self.access(body)['status'], 'inactive')
        finally:
            self.admin('console', "UPDATE memberships SET active=true WHERE workspace_id='ws_a' AND subject='owner_a'", ())
        body, intent, case, proposal, csrf, decision = self.fixture()
        self.http.post(self.base + '/sessions/revoke', headers=csrf).raise_for_status()
        self.assertEqual(self.execute(proposal)['last_error'], 'approval_authority_revoked')
        self.assertEqual(self.access(body)['status'], 'inactive')

    def test_05_process_death_after_remote_commit_recovers_same_identity(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        # Separate Python worker dies after a real target transaction commits.
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash-once', proposal['payload']['operation_id']], cwd=ROOT, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 73)
        self.assertEqual(self.access(body)['revision'], 1)
        identifier = proposal['payload']['operation_id']
        self.admin('console', "UPDATE repair_operations SET lease_until=now()-interval '1 second',due_at=now() WHERE operation_id=%s", (identifier,))
        # Force all other fixture work out of this recovery round.
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('UPDATE repair_operations SET due_at=now()+interval \'1 hour\' WHERE operation_id<>%s AND state=ANY(%s)', (identifier, ['queued','executing','verifying','outcome_unknown']))
        op = claim_repair(self.database, 'ws_a')
        self.assertEqual(op['operation_id'], identifier)
        self.assertEqual(op['state'], 'outcome_unknown')
        execute_repair(self.app, op)
        self.assertEqual(self.operation(identifier)['state'], 'succeeded')
        self.assertEqual(self.access(body)['revision'], 1)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("SELECT count(*) AS n FROM repair_attempts WHERE operation_id=%s AND kind='dispatch'", (identifier,))
            self.assertEqual(cursor.fetchone()['n'], 1)

    def test_06_missing_receipt_stays_unknown_and_blocks_new_repair(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        identifier = proposal['payload']['operation_id']
        self.admin('console', "UPDATE repair_operations SET dispatch_started_at=now(),state='outcome_unknown' WHERE operation_id=%s", (identifier,))
        result = self.execute(proposal)
        self.assertEqual(result['state'], 'outcome_unknown')
        self.assertEqual(self.access(body)['revision'], 0)
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'], 'outcome_unknown')
        self.refresh(intent)
        c = self.cases(body['purchase_id'])[0]
        self.assertEqual(self.http.post(self.base + f"/cases/{c['case_id']}/proposals", headers=csrf,
            json={'reason': 'Try another repair', 'observation_id': c['latest_observation_id'], 'fingerprint': c['fingerprint']}).status_code, 409)
        self.http.post(self.base + f'/operations/{identifier}/recover', headers=csrf).raise_for_status()

    def test_07_normal_fulfillment_race_yields_one_target_transition(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        original = self.http.stream
        @contextmanager
        def racing(method, url, **kwargs):
            if method == 'POST' and url.endswith('/internal/access-grants'):
                self.grant_independently(body)
            with original(method, url, **kwargs) as response:
                yield response
        with patch.object(self.http, 'stream', racing):
            result = self.execute(proposal)
        self.assertEqual(result['state'], 'conflict')
        self.assertEqual(self.access(body)['revision'], 1)
        self.refresh(intent)
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'], 'resolved')

    def test_08_grant_receipt_is_historical_not_current_recovery(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        original = self.http.stream
        @contextmanager
        def suspended_after_commit(method, url, **kwargs):
            with original(method, url, **kwargs) as response:
                yield response
            if method == 'POST' and url.endswith('/internal/access-grants'):
                self.admin('reference', "UPDATE access_grants SET status='suspended',revision=revision+1 WHERE purchase_id=%s", (body['purchase_id'],))
        with patch.object(self.http, 'stream', suspended_after_commit):
            result = self.execute(proposal)
        self.assertEqual(result['receipt']['result'], 'granted')
        self.assertEqual(result['state'], 'applied_not_recovered')
        self.assertNotEqual(self.cases(body['purchase_id'])[0]['state'], 'resolved')

    def test_09_identity_approval_and_attempt_history_are_immutable(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        for sql in ('UPDATE repair_proposals SET payload=\'{}\' WHERE proposal_id=%s',
                    'UPDATE repair_approvals SET reason=\'changed\' WHERE proposal_id=%s',
                    'DELETE FROM repair_approvals WHERE proposal_id=%s'):
            with self.assertRaises(psycopg2.Error):
                with self.database.transaction('ws_a') as cursor:
                    cursor.execute(sql, (proposal['proposal_id'],))
        with self.database.transaction('ws_b') as cursor:
            cursor.execute('SELECT * FROM repair_proposals WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertIsNone(cursor.fetchone())
        op = self.lease_operation(proposal)
        self.admin('console', "UPDATE repair_operations SET lease_until=now()-interval '1 second' WHERE operation_id=%s", (op['operation_id'],))
        with self.assertRaises(ReadFailure):
            execute_repair(self.app, op)
        self.assertEqual(self.access(body)['revision'], 0)

    def test_10_payload_digest_and_invalid_receipt_are_rejected(self):
        body, intent, case, proposal, csrf, decision = self.fixture()
        self.assertFalse(valid_receipt({'result': 'granted', 'revision': 1}, proposal['payload']))
        self.assertFalse(valid_receipt({'workspace_id': 'ws_b'}, proposal['payload']))
        self.assertEqual(self.http.get(self.base + f"/cases/{case['case_id']}/repairs").headers['Cache-Control'], 'no-store')

    def test_11_expiry_and_policy_change_block_before_dispatch(self):
        class FutureClock:
            @staticmethod
            def now(zone):
                return datetime.now(zone) + timedelta(minutes=11)
        for patched in ('expiry', 'policy'):
            with self.subTest(patched=patched):
                body, intent, case, proposal, csrf, decision = self.fixture()
                target = 'backend.app.repairs.datetime' if patched == 'expiry' else 'backend.app.repairs.POLICY_VERSION'
                with patch(target, FutureClock if patched == 'expiry' else 'new_policy_v2'):
                    result = self.execute(proposal)
                self.assertEqual(result['state'], 'blocked')
                self.assertIsNone(result['dispatch_started_at'])
                self.assertEqual(self.access(body)['revision'], 0)

    def test_12_approval_and_operation_enqueue_rollback_together(self):
        body, intent, case, proposal, csrf, decision = self.fixture(False)
        @contextmanager
        def failed_commit(workspace, subject=''):
            with self.database.transaction(workspace, subject) as cursor:
                yield cursor
                raise psycopg2.OperationalError('Injected pre-commit failure')
        broken = SimpleNamespace(state=SimpleNamespace(database=SimpleNamespace(transaction=failed_commit)))
        request = SimpleNamespace(app=broken, cookies={'payment_session': self.http.cookies.get('payment_session')})
        with patch('backend.app.repairs.actor', return_value='owner_a'):
            with self.assertRaises(psycopg2.OperationalError):
                decide('ws_a', proposal['proposal_id'], ProposalDecision(**decision), request)
        with self.database.transaction('ws_a') as cursor:
            for table in ('repair_approvals', 'repair_operations'):
                cursor.execute(f'SELECT count(*) AS n FROM {table} WHERE proposal_id=%s', (proposal['proposal_id'],))
                self.assertEqual(cursor.fetchone()['n'], 0)
        self.http.post(self.base + f"/proposals/{proposal['proposal_id']}/decisions", headers=csrf, json=decision).raise_for_status()

    def test_13_expired_preview_cannot_be_approved(self):
        class PastClock:
            @staticmethod
            def now(zone):
                return datetime.now(zone) - timedelta(minutes=11)
        body, intent = self.overdue()
        case = self.cases(body['purchase_id'])[0]
        csrf = self.login()
        request = SimpleNamespace(app=self.app)
        with patch('backend.app.repairs.actor', return_value='owner_a'), patch('backend.app.repairs.datetime', PastClock):
            proposal = propose('ws_a', case['case_id'], Dismissal(reason='Review an expired fixture', observation_id=case['latest_observation_id'], fingerprint=case['fingerprint']), request)
        response = self.http.post(self.base + f"/proposals/{proposal['proposal_id']}/decisions", headers=csrf,
            json={'decision':'approve','payload_digest':proposal['payload_digest'],'reason':'Review exact expired target'})
        self.assertEqual(response.status_code, 409)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT 1 FROM repair_operations WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertIsNone(cursor.fetchone())

    def test_14_two_different_actors_approve_one_operation(self):
        body, intent, case, proposal, csrf, decision = self.fixture(False)
        url = self.base + f"/proposals/{proposal['proposal_id']}/decisions"
        with httpx.Client(timeout=8, trust_env=False) as owner, httpx.Client(timeout=8, trust_env=False) as operator:
            requests = []
            for client, subject in ((owner, 'owner_a'), (operator, 'operator_a')):
                login = client.post('http://127.0.0.1:8000/dev/sessions/' + subject, headers={'X-Demo-Login-Key': self.env['DEMO_LOGIN_KEY']})
                login.raise_for_status()
                requests.append((client, {'X-CSRF-Token': login.json()['csrf_token']}))
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(lambda item: item[0].post(url, headers=item[1], json=decision), requests))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS n FROM repair_operations WHERE proposal_id=%s', (proposal['proposal_id'],))
            self.assertEqual(cursor.fetchone()['n'], 1)
        self.assertEqual(self.execute(proposal)['state'], 'succeeded')
        self.assertEqual(self.access(body)['revision'], 1)


def crash_once(identifier):
    Phase4IntegrationTests.setUpClass()
    test = Phase4IntegrationTests()
    op = test.operation(identifier)
    with test.database.transaction('ws_a') as cursor:
        cursor.execute("UPDATE repair_operations SET lease_token=%s,lease_until=now()+interval '30 seconds',attempts=attempts+1 WHERE operation_id=%s RETURNING *", (uuid.uuid4().hex, identifier))
        op = dict(cursor.fetchone())
    original = test.http.stream
    @contextmanager
    def crash(method, url, **kwargs):
        with original(method, url, **kwargs) as response:
            yield response
        if method == 'POST' and url.endswith('/internal/access-grants'):
            os._exit(73)
    test.http.stream = crash
    execute_repair(test.app, op)
    raise SystemExit(74)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--crash-once':
        crash_once(sys.argv[2])
    subprocess.run(['docker','compose','stop',*WORKERS], cwd=ROOT, check=True, capture_output=True)
    try:
        result = unittest.main(verbosity=2, exit=False, defaultTest='Phase4IntegrationTests').result
    finally:
        subprocess.run(['docker','compose','start',*WORKERS], cwd=ROOT, check=True, capture_output=True)
    sys.exit(0 if result.wasSuccessful() else 1)
