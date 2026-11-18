"""Public Scope & Pay workflow tests against an isolated PostgreSQL database.

All model/payment adapters are local fixtures. No external model calls, PayPal
requests, emails or money movement. The running application database is untouched.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch
import uuid

import httpx
import psycopg2
from psycopg2 import sql
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.config import Settings
from backend.app.main import create_app
from backend.app.paypal_provider import PayPalSandboxConnection
from backend.app.scope_ai import SAMPLE_MESSAGES
from backend.app.scope_invoice_worker import run_once
from backend.app.scope_invoicing import InvoiceError
from scripts.check_phase1 import local_environment
from scripts.migrate import migrate
from scripts.restore_drill import admin_url, create_scratch


class ScopeDatabaseContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = local_environment()
        cls.scratch = create_scratch(cls.env)
        cls.addClassCleanup(cls.drop_scratch)
        migrate('console', admin_url(cls.env, cls.scratch))

    @classmethod
    def drop_scratch(cls):
        if not cls.scratch.startswith('release_drill_'):
            raise ValueError('Unexpected scratch database name')
        connection = psycopg2.connect(admin_url(cls.env, 'postgres'))
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.scratch)))
        finally:
            connection.close()

    def setUp(self):
        self.workspace = 'scope_' + uuid.uuid4().hex
        self.other = 'scope_other_' + uuid.uuid4().hex
        self.keys = {ws: {purpose: secrets.token_hex(32) for purpose in ('registration', 'provider', 'adapter', 'webhook')}
                     for ws in (self.workspace, self.other)}
        connection = PayPalSandboxConnection('fixture-client-id', 'fixture-client-secret', 'YXZY75W2GKDQE')
        self.settings = Settings('console', f"postgresql://console_runtime:{self.env['CONSOLE_DB_PASSWORD']}@127.0.0.1:{self.env.get('POSTGRES_PORT', '15432')}/{self.scratch}",
            secrets.token_hex(32), self.keys, paypal={self.workspace: connection})
        self.app = create_app('console', self.settings)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.db = self.app.state.database
        with psycopg2.connect(admin_url(self.env, self.scratch)) as connection:
            with connection.cursor() as cursor:
                for workspace in (self.workspace, self.other):
                    for subject, role in (('owner_a', 'owner'), ('viewer_a', 'viewer')):
                        cursor.execute('INSERT INTO memberships(workspace_id,subject,role) VALUES (%s,%s,%s)', (workspace, subject, role))
        self.login('owner_a')
        self.base = f'/api/workspaces/{self.workspace}/scope'
        # Fail loudly if a regression accidentally reaches an external provider.
        self.transport = httpx.Client(transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(AssertionError('Unexpected provider request'))))
        self.addCleanup(self.transport.close)
        self.app.state.http = self.transport

    def login(self, subject):
        response = self.client.post('/dev/sessions/' + subject, headers={'X-Demo-Login-Key': self.settings.demo_login_key})
        self.assertEqual(response.status_code, 200, response.text)
        self.auth = {'X-CSRF-Token': response.json()['csrf_token']}

    def post(self, path, body=None, status=200, headers=None):
        response = self.client.post(path, json={} if body is None else body, headers=self.auth if headers is None else headers)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def seed(self):
        result = self.post(self.base + '/demo')
        self.path = self.base + '/projects/' + result['project_id']
        return result

    def proposal(self, project=None):
        project = self.seed() if project is None else project
        body = {'title': 'Contact form', 'description': 'Build and connect one contact form', 'amount_minor': 12000,
            'evidence': [{'message_id': project['messages'][2]['message_id'], 'quote': SAMPLE_MESSAGES[2]}],
            'expected_brief_revision': project['brief_revision']}
        result = self.post(self.path + '/proposals', body)
        return result, result['proposals'][0], body

    def share(self, proposal):
        result = self.post(self.path + '/proposals/' + proposal['proposal_id'] + '/share', {'expected_version': proposal['version']})
        token = result['share_url'].rsplit('/', 1)[-1]
        return token

    def review(self, token):
        return self.client.get('/api/scope/review', headers={'Authorization': 'Bearer ' + token})

    def decision(self, token, body, status=200):
        return self.post('/api/scope/review/decision', body, status=status, headers={'Authorization': 'Bearer ' + token})

    def accept(self, proposal=None):
        if proposal is None:
            _, proposal, _ = self.proposal()
        link = self.share(proposal)
        decision = {'decision': 'accepted', 'name': 'Alex', 'proposal_version': proposal['version'], 'proposal_digest': proposal['proposal_digest']}
        self.decision(link, decision)
        return proposal, link, decision

    def invoice(self, mode='local'):
        proposal, _, _ = self.accept()
        data = self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': mode})
        return data['invoices'][0], proposal

    def test_full_local_visible_workflow_and_idempotent_import(self):
        first = self.seed()
        again = self.post(self.base + '/demo')
        self.assertEqual(first['project_id'], again['project_id'])
        self.assertEqual([m['text'] for m in first['messages']], list(SAMPLE_MESSAGES))
        repeated = self.post(self.path + '/messages', {'text': SAMPLE_MESSAGES[0]})
        self.assertEqual(first['messages'], repeated['messages'])
        review = self.post(self.path + '/analysis', {'mode': 'sample'})
        self.assertEqual([c['classification'] for c in review['analysis']['candidates']], ['included', 'unclear', 'addition'])
        self.assertEqual(review['proposals'], [])
        invoice, proposal = self.invoice()
        self.assertEqual(invoice['status'], 'draft')
        self.assertTrue(run_once(self.app, self.workspace))
        current = self.client.get(self.path).json()
        self.assertEqual(current['invoices'][0]['status'], 'unpaid')
        paid = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/demo-pay')
        self.assertEqual(paid['invoices'][0]['status'], 'paid')
        repeated_pay = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/demo-pay')
        self.assertEqual(len(paid['events']), len(repeated_pay['events']))
        duplicate = self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'local'})
        self.assertEqual(len(duplicate['invoices']), 1)
        self.assertFalse(run_once(self.app, self.workspace))

    def test_viewer_csrf_tenant_and_runtime_rls_are_enforced(self):
        project = self.seed()
        self.post(self.path + '/messages', {'text': 'Forbidden missing CSRF'}, headers={}, status=403)
        self.login('viewer_a')
        self.post(self.base + '/demo', status=403)
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(self.client.get(f'/api/workspaces/{self.other}/scope/projects/' + project['project_id']).status_code, 404)
        with self.db.transaction(self.other) as cursor:
            cursor.execute('SELECT count(*) AS count FROM scope_projects')
            self.assertEqual(cursor.fetchone()['count'], 0)
        with self.db.transaction() as cursor:
            cursor.execute('SELECT count(*) AS count FROM scope_messages')
            self.assertEqual(cursor.fetchone()['count'], 0)
            cursor.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname LIKE 'scope_%' AND relkind='r' AND relname!='scope_capability_directory'")
            self.assertTrue(all(row['relrowsecurity'] and row['relforcerowsecurity'] for row in cursor.fetchall()))

    def test_citations_must_be_actual_project_sources(self):
        project, proposal, body = self.proposal()
        self.post(self.path + '/proposals', body | {'evidence': [{'message_id': 'unrelated', 'quote': SAMPLE_MESSAGES[2]}]}, status=422)
        self.post(self.path + '/proposals', body | {'evidence': [{'message_id': project['messages'][2]['message_id'], 'quote': 'Fabricated approval'}]}, status=422)
        self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'local'}, status=409)

    def test_sample_cannot_pretend_to_review_changed_or_custom_data(self):
        self.seed()
        self.post(self.path + '/messages', {'text': 'Different source'})
        self.post(self.path + '/analysis', {'mode': 'sample'}, status=409)
        with patch.dict('os.environ', {'OPENAI_API_KEY': '', 'OPENAI_MODEL': ''}):
            self.post(self.path + '/analysis', {'mode': 'openai'}, status=503)

    def test_gemini_reviews_preserve_provider_and_require_selected_configuration(self):
        project = self.seed()
        review = {'summary': 'Confirm the included revision.', 'candidates': [
            {'title': 'Headline revision', 'classification': 'included', 'rationale': 'One revision is included.',
             'evidence': [{'message_id': project['messages'][0]['message_id'], 'quote': SAMPLE_MESSAGES[0]}]}]}
        response = {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model',
            'parts': [{'text': json.dumps(review)}]}}]}
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=response)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        self.app.state.http = client
        with patch.dict('os.environ', {'AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'fixture-google-key',
                                      'GEMINI_MODEL': 'gemini-3.1-flash-lite'}):
            self.post(self.path + '/analysis', {'mode': 'openai'}, status=503)
            saved = self.post(self.path + '/analysis', {'mode': 'gemini'})
        self.assertEqual(saved['analysis']['mode'], 'gemini')
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.host, 'generativelanguage.googleapis.com')

    def test_share_discloses_only_review_fields_and_forged_expired_reissued_links_fail(self):
        project, proposal, _ = self.proposal()
        old = self.share(proposal)
        exposed = self.review(old).json()
        self.assertEqual(set(exposed), {'project_name', 'client_name', 'brief', 'proposal', 'expires_at'})
        self.assertNotIn('client_email', str(exposed))
        self.assertNotIn(SAMPLE_MESSAGES[1], str(exposed))
        self.assertEqual(self.review('z' * 43).status_code, 404)
        self.assertEqual(self.review('short').status_code, 404)
        self.assertEqual(self.client.get('/api/scope/review').status_code, 404)
        new = self.share(proposal)
        self.assertEqual(self.review(old).status_code, 410)
        # Only the scratch-database administrator changes time fixtures; the
        # runtime cannot rewrite an issued link's immutable expiry/snapshot.
        with psycopg2.connect(admin_url(self.env, self.scratch)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE scope_shares SET expires_at=now()-interval '1 second' WHERE workspace_id=%s AND revoked_at IS NULL", (self.workspace,))
        self.assertEqual(self.review(new).status_code, 410)

    def test_exact_client_decision_is_explicit_idempotent_and_first_decision_wins(self):
        _, proposal, _ = self.proposal()
        link = self.share(proposal)
        body = {'decision': 'accepted', 'name': 'Alex', 'proposal_version': proposal['version'], 'proposal_digest': proposal['proposal_digest']}
        self.decision(link, body | {'proposal_digest': 'f' * 64}, status=409)
        self.decision(link, body | {'proposal_version': 2}, status=409)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.client.post('/api/scope/review/decision', json=body, headers={'Authorization': 'Bearer ' + link}), range(2)))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.decision(link, body | {'decision': 'declined'}, status=409)
        detail = self.client.get(self.path).json()
        self.assertEqual(sum(event['kind'] == 'client_accepted' for event in detail['events']), 1)

    def test_link_can_be_revoked_without_rewriting_recorded_acceptance(self):
        _, proposal, _ = self.proposal()
        _, link, _ = self.accept(proposal)
        detail = self.post(self.path + '/proposals/' + proposal['proposal_id'] + '/share/revoke')
        self.assertEqual(detail['proposals'][0]['status'], 'accepted')
        self.assertEqual(self.review(link).status_code, 410)
        self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'local'})

    def test_proposal_and_brief_edits_invalidate_old_acceptance(self):
        _, proposal, original = self.proposal()
        _, link, decision = self.accept(proposal)
        patch_body = original | {'expected_version': 1, 'amount_minor': 15000}
        changed = self.client.patch(self.path + '/proposals/' + proposal['proposal_id'], json=patch_body, headers=self.auth)
        self.assertEqual(changed.status_code, 200, changed.text)
        revised = changed.json()['proposals'][0]
        self.assertEqual(revised['status'], 'draft')
        self.assertIsNone(revised['accepted_at'])
        self.assertNotEqual(revised['proposal_digest'], proposal['proposal_digest'])
        agreement = changed.json()['agreements'][0]
        self.assertEqual(agreement['decision'], 'accepted')
        self.assertEqual(agreement['decision_name'], 'Alex')
        self.assertEqual(agreement['proposal_snapshot']['proposal']['amount_minor'], 12000)
        self.assertEqual(agreement['proposal_snapshot']['proposal']['version'], 1)
        self.assertEqual(agreement['proposal_snapshot']['proposal']['proposal_digest'], proposal['proposal_digest'])
        self.assertNotIn('token_digest', agreement)
        self.assertEqual(self.review(link).status_code, 410)
        self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'local'}, status=409)
        self.assertEqual(self.client.patch(self.path + '/proposals/' + proposal['proposal_id'], json=patch_body, headers=self.auth).status_code, 409)
        second_link = self.share(revised)
        revised_brief = self.post(self.path + '/brief', {'brief': 'Updated landing page agreement', 'expected_revision': 1})
        self.assertEqual(revised_brief['brief_revision'], 2)
        self.assertEqual(revised_brief['proposals'][0]['status'], 'superseded')
        self.assertEqual(self.review(second_link).status_code, 410)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute("SELECT proposal_snapshot,decision,decision_name FROM scope_shares WHERE proposal_id=%s AND decision='accepted'", (proposal['proposal_id'],))
            prior = cursor.fetchone()
            self.assertEqual(prior['decision_name'], 'Alex')
            self.assertEqual(prior['proposal_snapshot']['proposal']['amount_minor'], 12000)
            self.assertEqual(prior['proposal_snapshot']['proposal']['version'], 1)
            self.assertEqual(prior['proposal_snapshot']['proposal']['proposal_digest'], proposal['proposal_digest'])
            self.assertEqual(prior['proposal_snapshot']['brief'], 'One landing page for $500, including one round of revisions.')
            cursor.execute("SELECT has_column_privilege(current_user,'scope_shares','proposal_snapshot','UPDATE') AS mutable")
            self.assertFalse(cursor.fetchone()['mutable'])

    def test_openai_rate_reservations_prevent_duplicate_spend_and_survive_failure(self):
        sample = self.seed()
        reviewed = {'mode': 'openai', 'summary': 'Fixture review', 'candidates': []}
        with patch('backend.app.scope_ai.configuration', return_value={'mode': 'openai'}), patch('backend.app.scope_ai.analyze', return_value=reviewed) as adapter:
            self.post(self.path + '/analysis', {'mode': 'openai'})
            response = self.client.post(self.path + '/analysis', json={'mode': 'openai'}, headers=self.auth)
            self.assertEqual(response.status_code, 429)
            self.assertGreater(int(response.headers['Retry-After']), 0)
            self.assertEqual(adapter.call_count, 1)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT count(*) AS count FROM scope_analysis_requests')
            self.assertEqual(cursor.fetchone()['count'], 1)

    def test_workspace_ai_quota_cannot_be_bypassed_by_switching_projects(self):
        reviewed = {'mode': 'openai', 'summary': 'Fixture review', 'candidates': []}
        project_body = {'name': 'Client site', 'client_name': 'Alex', 'client_email': 'alex@example.test',
                        'brief': 'One landing page', 'base_amount_minor': 50000}
        with patch('backend.app.scope_ai.configuration', return_value={'mode': 'openai'}), patch('backend.app.scope_ai.analyze', return_value=reviewed) as adapter:
            for index in range(7):
                project = self.post(self.base + '/projects', project_body)
                path = self.base + '/projects/' + project['project_id']
                self.post(path + '/messages', {'text': 'Please add a form'})
                self.post(path + '/analysis', {'mode': 'openai'}, status=200 if index < 6 else 429)
            self.assertEqual(adapter.call_count, 6)

    def test_concurrent_invoice_requests_and_workers_create_one_logical_invoice(self):
        proposal, _, _ = self.accept()
        body = {'proposal_id': proposal['proposal_id'], 'mode': 'local'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.client.post(self.path + '/invoices', json=body, headers=self.auth), range(2)))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json()['invoices'][0]['invoice_id'], responses[1].json()['invoices'][0]['invoice_id'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: run_once(self.app, self.workspace), range(2)))
        result = self.client.get(self.path).json()
        self.assertEqual(len(result['invoices']), 1)
        self.assertEqual(result['invoices'][0]['status'], 'unpaid')
        self.assertEqual(sum(event['kind'] == 'invoice_created' for event in result['events']), 1)

    def test_sensitive_share_and_invoice_require_recent_confirmation(self):
        _, proposal, _ = self.proposal()
        with self.db.transaction() as cursor:
            cursor.execute("UPDATE sessions SET authenticated_at=now()-interval '31 minutes' WHERE subject='owner_a'")
        self.post(self.path + '/proposals/' + proposal['proposal_id'] + '/share', {'expected_version': 1}, status=428)

    def test_paypal_payment_link_activation_is_explicit_and_does_not_repeat(self):
        invoice, _ = self.invoice('paypal_sandbox')
        draft = {'provider_invoice_id': 'INV2-AAAA-BBBB-CCCC-DDDD', 'status': 'draft', 'amount_minor': 12000, 'currency': 'usd', 'payment_url': None}
        with patch('backend.app.scope_invoicing.create_draft', return_value=draft):
            run_once(self.app, self.workspace)
        response = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate')
        self.assertEqual(response['invoices'][0]['status'], 'creating')
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate')
        payable = draft | {'status': 'unpaid', 'payment_url': 'https://www.sandbox.paypal.com/invoice/p/fixture'}
        with patch('backend.app.scope_invoicing.activate_invoice', return_value=payable) as adapter:
            run_once(self.app, self.workspace)
            self.assertFalse(run_once(self.app, self.workspace))
            self.assertEqual(adapter.call_count, 1)
        current = self.client.get(self.path).json()
        self.assertEqual(current['invoices'][0]['status'], 'unpaid')
        self.assertEqual(current['invoices'][0]['provider_invoice_id'], draft['provider_invoice_id'])
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate', status=409)

    def test_uncertain_activation_keeps_id_and_draft_refresh_cannot_enable_resend(self):
        invoice, _ = self.invoice('paypal_sandbox')
        draft = {'provider_invoice_id': 'INV2-AAAA-BBBB-CCCC-DDDD', 'status': 'draft', 'amount_minor': 12000, 'currency': 'usd', 'payment_url': None}
        with patch('backend.app.scope_invoicing.create_draft', return_value=draft):
            run_once(self.app, self.workspace)
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate')
        with patch('backend.app.scope_invoicing.activate_invoice', side_effect=InvoiceError('timeout', uncertain=True)) as adapter:
            run_once(self.app, self.workspace)
            self.assertFalse(run_once(self.app, self.workspace))
            self.assertEqual(adapter.call_count, 1)
        with patch('backend.app.scope_invoicing.read_invoice', return_value=draft):
            result = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh')
        self.assertEqual(result['invoices'][0]['status'], 'outcome_unknown')
        self.assertEqual(result['invoices'][0]['provider_invoice_id'], draft['provider_invoice_id'])
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate', status=409)
        with patch('backend.app.scope_invoicing.read_invoice', return_value=draft | {'status': 'unpaid'}):
            result = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh')
        self.assertEqual(result['invoices'][0]['status'], 'outcome_unknown')
        self.assertEqual(result['invoices'][0]['last_error'], 'activation_outcome_unknown')
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/activate', status=409)
        payment_url = 'https://www.sandbox.paypal.com/invoice/p/fixture'
        with patch('backend.app.scope_invoicing.read_invoice', return_value=draft | {'status': 'unpaid', 'payment_url': payment_url}):
            result = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh')
        self.assertEqual(result['invoices'][0]['status'], 'unpaid')
        self.assertEqual(result['invoices'][0]['payment_url'], payment_url)
        self.assertIsNone(result['invoices'][0]['last_error'])
        with patch('backend.app.scope_invoicing.read_invoice', return_value=draft | {'status': 'paid'}):
            result = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh')
        self.assertEqual(result['invoices'][0]['status'], 'paid')

    def test_existing_invoice_preserves_scope_and_local_cannot_mutate_paypal(self):
        invoice, proposal = self.invoice('paypal_sandbox')
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/demo-pay', status=409)
        self.post(self.path + '/brief', {'brief': 'Rewrite the billed agreement', 'expected_revision': 1}, status=409)
        project = self.client.get(self.path).json()
        body = {'title': 'Changed', 'description': 'Changed', 'amount_minor': 2, 'evidence': proposal['evidence'],
                'expected_brief_revision': 1, 'expected_version': 1}
        self.assertEqual(self.client.patch(self.path + '/proposals/' + proposal['proposal_id'], json=body, headers=self.auth).status_code, 409)
        self.post(self.path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'local'}, status=409)

    def test_paypal_success_and_uncertain_create_are_not_repeated(self):
        invoice, _ = self.invoice('paypal_sandbox')
        with patch('backend.app.scope_invoicing.create_draft', side_effect=InvoiceError('fixture_timeout', uncertain=True)) as adapter:
            self.assertTrue(run_once(self.app, self.workspace))
            self.assertFalse(run_once(self.app, self.workspace))
            self.assertEqual(adapter.call_count, 1)
        detail = self.client.get(self.path).json()
        self.assertEqual(detail['invoices'][0]['status'], 'outcome_unknown')
        self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh', status=409)

    def test_restart_after_claim_recovers_unknown_and_fences_late_worker(self):
        invoice, _ = self.invoice('paypal_sandbox')
        def late_result(*args):
            with self.db.transaction(self.workspace) as cursor:
                cursor.execute("UPDATE scope_invoice_jobs SET lease_until=now()-interval '1 second' WHERE invoice_id=%s", (invoice['invoice_id'],))
            self.assertTrue(run_once(self.app, self.workspace))
            return {'provider_invoice_id': 'INV2-AAAA-BBBB-CCCC-DDDD', 'status': 'draft', 'amount_minor': 12000, 'currency': 'usd', 'payment_url': None}
        with patch('backend.app.scope_invoicing.create_draft', side_effect=late_result) as adapter:
            self.assertTrue(run_once(self.app, self.workspace))
            self.assertFalse(run_once(self.app, self.workspace))
            self.assertEqual(adapter.call_count, 1)
        detail = self.client.get(self.path).json()
        self.assertEqual(detail['invoices'][0]['status'], 'outcome_unknown')
        self.assertIsNone(detail['invoices'][0]['provider_invoice_id'])

    def test_paypal_connection_swap_and_missing_credentials_fail_before_dispatch(self):
        invoice, _ = self.invoice('paypal_sandbox')
        original = self.settings.paypal[self.workspace]
        self.settings.paypal[self.workspace] = PayPalSandboxConnection('different-client', 'different-secret', 'ABCDE12345678')
        with patch('backend.app.scope_invoicing.create_draft') as adapter:
            run_once(self.app, self.workspace)
            adapter.assert_not_called()
        detail = self.client.get(self.path).json()
        self.assertEqual(detail['invoices'][0]['status'], 'failed')
        self.assertEqual(detail['invoices'][0]['last_error'], 'paypal_connection_changed')

    def test_paypal_create_success_checks_exact_result_and_refresh_binding(self):
        invoice, _ = self.invoice('paypal_sandbox')
        result = {'provider_invoice_id': 'INV2-AAAA-BBBB-CCCC-DDDD', 'status': 'draft', 'amount_minor': 12000, 'currency': 'usd', 'payment_url': None}
        with patch('backend.app.scope_invoicing.create_draft', return_value=result) as adapter:
            self.assertTrue(run_once(self.app, self.workspace))
            self.assertFalse(run_once(self.app, self.workspace))
            self.assertEqual(adapter.call_count, 1)
        with patch('backend.app.scope_invoicing.read_invoice', return_value=result | {'status': 'paid'}):
            detail = self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh')
        self.assertEqual(detail['invoices'][0]['status'], 'paid')
        with patch('backend.app.scope_invoicing.read_invoice', return_value=result | {'amount_minor': 1}):
            self.post(self.path + '/invoices/' + invoice['invoice_id'] + '/refresh', status=502)


if __name__ == '__main__':
    unittest.main(verbosity=2)
