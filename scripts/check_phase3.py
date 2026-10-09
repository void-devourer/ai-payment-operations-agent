"""Real PostgreSQL/HTTP detection and independent reconciliation checks.

Workers pause during fault fixtures. Only test-specific success clocks/target
states are changed through the test admin connection; production has no such API.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC,datetime,timedelta
import subprocess
import sys
import unittest
import uuid
from types import SimpleNamespace

import psycopg2

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_phase2 import Phase2IntegrationTests,WORKERS
from backend.app.evidence import collect
from backend.app.jobs import enqueue,fail,ReadFailure
from backend.app.reconciliation import schedule_page


class Phase3IntegrationTests(unittest.TestCase):
    setUpClass=classmethod(Phase2IntegrationTests.setUpClass.__func__)
    tearDownClass=classmethod(Phase2IntegrationTests.tearDownClass.__func__)
    headers=Phase2IntegrationTests.headers
    purchase=Phase2IntegrationTests.purchase
    lease=Phase2IntegrationTests.lease
    facts=Phase2IntegrationTests.facts
    event=Phase2IntegrationTests.event
    send=Phase2IntegrationTests.send

    def admin(self,database,sql,params):
        port=self.env.get('POSTGRES_PORT','15432')
        with psycopg2.connect(f"postgresql://postgres:{self.env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/{database}",connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql,params)

    def refresh(self,intent):
        with self.database.transaction('ws_a') as cursor:
            enqueue(cursor,'ws_a','sim_ws_a',intent)
        collect(self.app,self.lease(intent))

    def overdue(self):
        body,intent=self.purchase()
        collect(self.app,self.lease(intent))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT outcome FROM evaluations WHERE purchase_id=%s',(body['purchase_id'],))
            self.assertEqual(cursor.fetchone()['outcome'],'pending')
        self.admin('console',"UPDATE success_clocks SET first_confirmed_at=now()-interval '121 seconds' WHERE payment_intent_id=%s",(intent,))
        self.refresh(intent)
        return body,intent

    def cases(self,purchase):
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT * FROM cases WHERE purchase_id=%s ORDER BY generation',(purchase,))
            return cursor.fetchall()

    def login(self,subject='owner_a'):
        response=self.http.post('http://127.0.0.1:8000/dev/sessions/'+subject,headers={'X-Demo-Login-Key':self.env['DEMO_LOGIN_KEY']})
        response.raise_for_status()
        return {'X-CSRF-Token':response.json()['csrf_token']}

    def grant_independently(self,body):
        self.http.post('http://127.0.0.1:8001/internal/access-grants',headers=self.headers('ADAPTER'),json={
            'operation_id':'test_manual_'+uuid.uuid4().hex,'workspace_id':'ws_a','purchase_id':body['purchase_id'],
            'customer_id':body['customer_id'],'product_id':'digital_pass','expected_revision':0,
            'proposal_id':'test_external_fix','expires_at':(datetime.now(UTC)+timedelta(minutes=1)).isoformat()}).raise_for_status()

    def scan_until_job(self,intent):
        # No inbox lookup is involved. Durable pages may start from an interrupted scan.
        for _ in range(100):
            schedule_page(self.database,'ws_a','sim_ws_a',force=True)
            with self.database.transaction('ws_a') as cursor:
                cursor.execute("SELECT 1 FROM jobs WHERE payment_intent_id=%s AND state IN ('queued','retry_wait')",(intent,))
                if cursor.fetchone():
                    return
        self.fail('Bounded fixture scan did not reach the registered purchase')

    def test_01_success_clock_durable_grace_and_single_active_case(self):
        body,intent=self.overdue()
        before=self.cases(body['purchase_id'])
        self.assertEqual(len(before),1)
        self.assertEqual(before[0]['discrepancy_code'],'PAID_ACCESS_MISSING')
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT first_confirmed_at FROM success_clocks WHERE payment_intent_id=%s',(intent,))
            clock=cursor.fetchone()['first_confirmed_at']
        # Two purchase-specific jobs publish serially under the same purchase head.
        self.refresh(intent)
        self.assertEqual(self.cases(body['purchase_id'])[0]['case_id'],before[0]['case_id'])
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT first_confirmed_at FROM success_clocks WHERE payment_intent_id=%s',(intent,))
            self.assertEqual(cursor.fetchone()['first_confirmed_at'],clock)

    def test_02_dropped_event_is_found_without_inbox(self):
        body,intent=self.purchase()
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE jobs SET state='completed' WHERE payment_intent_id=%s",(intent,))
            cursor.execute('SELECT count(*) AS n FROM inbox WHERE payment_intent_id=%s',(intent,))
            self.assertEqual(cursor.fetchone()['n'],0)
        self.scan_until_job(intent)
        collect(self.app,self.lease(intent))
        self.assertTrue(self.facts(body['purchase_id'])['facts']['payment_complete'])

    def test_03_acknowledged_unprocessed_event_is_found_by_scan(self):
        body,intent=self.purchase()
        self.assertEqual(self.send(self.event(intent)).status_code,200)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE jobs SET state='completed' WHERE payment_intent_id=%s",(intent,))
        self.scan_until_job(intent)
        collect(self.app,self.lease(intent))
        self.assertTrue(self.facts(body['purchase_id'])['facts']['access_complete'])

    def test_04_independent_fix_resolves_only_missing_access(self):
        body,intent=self.overdue()
        self.grant_independently(body)
        self.refresh(intent)
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'],'resolved')
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/refunds',headers=self.headers(),
            json={'resource_id':'later_refund','status':'succeeded','amount_minor':1}).raise_for_status()
        self.admin('console',"UPDATE purchases SET registered_at=now()-interval '365 days' WHERE purchase_id=%s",(body['purchase_id'],))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE jobs SET state='completed' WHERE payment_intent_id=%s",(intent,))
        self.scan_until_job(intent)
        collect(self.app,self.lease(intent))
        cases=self.cases(body['purchase_id'])
        review=next(row for row in cases if row['discrepancy_code']=='REVERSAL_ACCESS_REVIEW')
        self.assertEqual(review['state'],'open')
        self.refresh(intent)
        self.assertEqual(next(row for row in self.cases(body['purchase_id']) if row['case_id']==review['case_id'])['state'],'open')

    def test_05_dismissal_suppression_material_change_and_authorization(self):
        body,intent=self.overdue()
        case=self.cases(body['purchase_id'])[0]
        url=f"http://127.0.0.1:8000/api/workspaces/ws_a/cases/{case['case_id']}"
        payload={'reason':'Customer requested an intentional exception','observation_id':case['latest_observation_id'],'fingerprint':case['fingerprint']}
        csrf=self.login('viewer_a')
        self.assertEqual(self.http.post(url+'/dismiss',headers=csrf,json=payload).status_code,403)
        csrf=self.login('owner_b')
        self.assertEqual(self.http.get(url).status_code,403)
        csrf=self.login()
        self.assertEqual(self.http.post(url+'/dismiss',json=payload).status_code,403)
        self.assertEqual(self.http.post(url+'/dismiss',headers=csrf,json=payload|{'fingerprint':'0'*64}).status_code,409)
        self.assertEqual(self.http.post(url+'/dismiss',headers=csrf,json=payload).status_code,200)
        self.refresh(intent)
        self.assertEqual(len(self.cases(body['purchase_id'])),1)
        self.assertEqual(self.cases(body['purchase_id'])[0]['state'],'dismissed')
        # A material target revision change permits a new missing-access generation.
        self.admin('reference','UPDATE access_grants SET revision=revision+1 WHERE purchase_id=%s',(body['purchase_id'],))
        self.refresh(intent)
        self.assertEqual([row['generation'] for row in self.cases(body['purchase_id'])],[1,2])

    def test_06_delayed_payment_and_intentional_suspension_never_eligible(self):
        body,intent=self.purchase(paid=False)
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'status':'processing'}).raise_for_status()
        collect(self.app,self.lease(intent))
        self.assertEqual(self.cases(body['purchase_id']),[])
        body,intent=self.overdue()
        self.admin('reference',"UPDATE access_grants SET status='suspended',revision=revision+1 WHERE purchase_id=%s",(body['purchase_id'],))
        self.refresh(intent)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT outcome,reasons FROM evaluations WHERE observation_id=%s',(self.facts(body['purchase_id'])['observation_id'],))
            row=cursor.fetchone()
            self.assertEqual(row['outcome'],'blocked')
            self.assertIn('intentional_access_block',row['reasons'])

    def test_07_incomplete_reads_expose_unknown_and_cannot_be_dismissed(self):
        body,intent=self.overdue()
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'read_fault':403}).raise_for_status()
        with self.assertRaises(ReadFailure):
            self.refresh(intent)
        case=self.cases(body['purchase_id'])[0]
        self.assertEqual(case['state'],'awaiting_evidence')
        csrf=self.login()
        url=f"http://127.0.0.1:8000/api/workspaces/ws_a/cases/{case['case_id']}"
        detail=self.http.get(url)
        detail.raise_for_status()
        self.assertFalse(detail.json()['evidence_fresh'])
        self.assertEqual(self.http.post(url+'/dismiss',headers=csrf,json={'reason':'Unable to investigate currently',
            'observation_id':case['latest_observation_id'],'fingerprint':case['fingerprint']}).status_code,409)
        coverage=self.http.get('http://127.0.0.1:8000/api/workspaces/ws_a/reconciliation').json()
        self.assertGreater(coverage['evidence_coverage']['incomplete'],0)
        self.assertEqual(coverage['provider_inventory_backfill'],'unsupported')

    def test_08_scan_checkpoint_and_enqueues_roll_back_together(self):
        body,intent=self.purchase()
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("SELECT run_id,after_purchase_id,scheduled_purchases FROM reconciliation_runs WHERE connection_id='sim_ws_a' AND state='scanning'")
            before=cursor.fetchall()
            cursor.execute('SELECT job_id,request_seq,state FROM jobs ORDER BY job_id')
            jobs_before=cursor.fetchall()
        @contextmanager
        def crash_before_commit(workspace):
            with self.database.transaction(workspace) as cursor:
                yield cursor
                raise RuntimeError('Injected scheduling commit failure')
        with self.assertRaises(RuntimeError):
            schedule_page(SimpleNamespace(transaction=crash_before_commit),'ws_a','sim_ws_a',force=True)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("SELECT run_id,after_purchase_id,scheduled_purchases FROM reconciliation_runs WHERE connection_id='sim_ws_a' AND state='scanning'")
            self.assertEqual(cursor.fetchall(),before)
            cursor.execute('SELECT job_id,request_seq,state FROM jobs ORDER BY job_id')
            self.assertEqual(cursor.fetchall(),jobs_before)
        self.scan_until_job(intent)

    def test_09_concurrent_observations_publish_one_review_case(self):
        body,intent=self.purchase()
        response=self.http.post('http://127.0.0.1:8002/internal/payments',headers=self.headers(),json={
            'purchase_id':body['purchase_id'],'customer_id':body['customer_id'],'amount_minor':2500,
            'currency':'usd','attempt_id':'second_attempt'})
        response.raise_for_status()
        second=response.json()['payment_intent_id']
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{second}/confirm',headers=self.headers()).raise_for_status()
        self.http.post(f"http://127.0.0.1:8000/api/purchases/{body['purchase_id']}/payment-attempts",
            headers=self.headers('REGISTRATION'),json={'payment_intent_id':second}).raise_for_status()
        jobs=[self.lease(intent),self.lease(second)]
        def publish_job(job):
            try:
                collect(self.app,job)
            except ReadFailure as error:
                self.assertEqual(error.code,'observation_superseded')
                fail(self.database,job,error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(publish_job,jobs))
        self.refresh(intent)
        cases=self.cases(body['purchase_id'])
        self.assertEqual(len(cases),1)
        self.assertEqual(cases[0]['discrepancy_code'],'PAYMENT_REVIEW')

    def test_10_investigation_reads_are_private_and_paginated(self):
        body,intent=self.overdue()
        case=self.cases(body['purchase_id'])[0]
        self.login()
        base='http://127.0.0.1:8000/api/workspaces/ws_a'
        detail=self.http.get(base+'/cases/'+case['case_id'])
        self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.headers['Cache-Control'],'no-store')
        self.assertIsNotNone(detail.json()['fresh_until'])
        history=self.http.get(base+f"/purchases/{body['purchase_id']}/timeline").json()['data']
        self.assertGreaterEqual(len(history),2)
        earlier=self.http.get(base+f"/purchases/{body['purchase_id']}/timeline?before_generation={history[0]['generation']}").json()['data']
        self.assertTrue(all(row['generation']<history[0]['generation'] for row in earlier))
        self.login('owner_b')
        for path in ('/cases','/cases/'+case['case_id'],f"/purchases/{body['purchase_id']}/timeline",'/reconciliation'):
            self.assertEqual(self.http.get(base+path).status_code,403)


if __name__=='__main__':
    subprocess.run(['docker','compose','stop',*WORKERS],cwd=ROOT,check=True,capture_output=True)
    try:
        result=unittest.main(verbosity=2,exit=False,defaultTest='Phase3IntegrationTests').result
    finally:
        subprocess.run(['docker','compose','start',*WORKERS],cwd=ROOT,check=True,capture_output=True)
    sys.exit(0 if result.wasSuccessful() else 1)
