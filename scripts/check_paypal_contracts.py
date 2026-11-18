"""Offline PayPal fixtures with real PostgreSQL, in an isolated scratch database.

No PayPal credentials or external requests. This is not real sandbox acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import copy
from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
import unittest
import uuid

import httpx
import psycopg2
from psycopg2 import sql
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests/unit'))
from test_paypal_investigation import ORDER,CAPTURE,SELLER,BUYER,WEBHOOK,order,capture,event,headers
from backend.app.config import Settings
from backend.app.evidence import collect
from backend.app.jobs import ReadFailure,claim,fail,enqueue_purchase
from backend.app.main import create_app
from backend.app.paypal_provider import PayPalSandboxConnection
from backend.app.paypal_ingestion import parse_event,persist
from backend.app.reconciliation import schedule_page
from scripts.check_phase1 import local_environment
from scripts.migrate import migrate
from scripts.restore_drill import admin_url,create_scratch


class PayPalDatabaseContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=local_environment()
        cls.scratch=create_scratch(cls.env)
        cls.addClassCleanup(cls.drop_scratch)
        migrate('console',admin_url(cls.env,cls.scratch))

    @classmethod
    def drop_scratch(cls):
        # Only remove this invocation's isolated database, after clients close.
        if not cls.scratch.startswith('release_drill_'): raise ValueError('Unexpected scratch database name')
        connection=psycopg2.connect(admin_url(cls.env,'postgres'))
        connection.autocommit=True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.scratch)))
        finally: connection.close()

    def setUp(self):
        self.workspace='ws_paypal_'+uuid.uuid4().hex
        self.other='ws_other_'+uuid.uuid4().hex
        self.purchase='p_'+uuid.uuid4().hex
        self.keys={ws:{purpose:secrets.token_hex(32) for purpose in ('registration','provider','adapter','webhook')}
                   for ws in (self.workspace,self.other)}
        cfg=PayPalSandboxConnection('fixture-client-id','fixture-client-secret',SELLER,webhook_id=WEBHOOK)
        other_cfg=PayPalSandboxConnection('other-client-id','other-client-secret','ABCDE12345678',webhook_id='OTHERWEBHOOK12345')
        settings=Settings('console',f"postgresql://console_runtime:{self.env['CONSOLE_DB_PASSWORD']}@127.0.0.1:{self.env.get('POSTGRES_PORT','15432')}/{self.scratch}",
                          secrets.token_hex(32),self.keys,paypal={self.workspace:cfg,self.other:other_cfg})
        self.app=create_app('console',settings)
        self.client=TestClient(self.app); self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.db=self.app.state.database
        self.registration={'workspace_id':self.workspace,'purchase_id':self.purchase,'customer_id':'c_fixture',
            'product_id':'digital_pass','expected_amount_minor':2500,'currency':'usd',
            'connection_id':'paypal_'+self.workspace,'provider_customer_id':BUYER}
        self.mode='normal'; self.calls=[]; self.orders=order(); self.capture=capture()
        self.transport=httpx.Client(transport=httpx.MockTransport(self.handle),trust_env=False)
        self.addCleanup(self.transport.close)
        self.app.state.http=self.transport
        for reader in self.app.state.paypal_webhook_readers.values(): reader.http=self.transport
        with psycopg2.connect(admin_url(self.env,self.scratch)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO memberships(workspace_id,subject,role) VALUES (%s,'owner_a','owner')",(self.workspace,))

    def handle(self,req):
        self.calls.append(req)
        path=req.url.path
        if path=='/v1/oauth2/token': return httpx.Response(200,json={'access_token':'fixture-token','token_type':'Bearer','expires_in':3600})
        if path=='/v1/notifications/verify-webhook-signature':
            if self.mode=='verification_unavailable': return httpx.Response(503)
            return httpx.Response(200,json={'verification_status':'FAILURE' if self.mode=='bad_signature' else 'SUCCESS'})
        if path.endswith('/orders/'+ORDER):
            body=copy.deepcopy(self.orders)
            if self.mode=='wrong_buyer': body['payer']['payer_id']='FOREIGNBUYER1'
            if self.mode=='changed_order' and sum(call.url.path==path for call in self.calls)>1:
                body['purchase_units'][0]['payments']['captures'][0]['status']='REFUNDED'
            if self.mode=='expired_lease':
                with self.db.transaction(self.workspace) as cursor:
                    cursor.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE purchase_id=%s AND state='leased'",(self.purchase,))
            return httpx.Response(200,json=body)
        if path.endswith('/captures/'+CAPTURE): return httpx.Response(200,json=self.capture)
        if path=='/internal/access/'+self.purchase:
            return httpx.Response(200,json={**{key:self.registration[key] for key in ('workspace_id','purchase_id','customer_id','product_id')},
                'status':'inactive','revision':0,'ever_activated':False,'complete':True})
        raise AssertionError('Unexpected fixture request: '+path)

    def registration_headers(self,ws=None):
        return {'Authorization':'Bearer '+self.keys[ws or self.workspace]['registration']}

    def register(self,with_capture=True):
        auth=self.registration_headers()
        self.assertEqual(self.client.post('/api/purchases',headers=auth,json=self.registration).status_code,200)
        self.assertEqual(self.client.post(f'/api/purchases/{self.purchase}/paypal-orders',headers=auth,json={'order_id':ORDER}).status_code,200)
        if with_capture:
            self.assertEqual(self.client.post(f'/api/purchases/{self.purchase}/paypal-captures',headers=auth,
                json={'order_id':ORDER,'capture_id':CAPTURE}).status_code,200)

    def send(self,body=None,raw=None,destination=None):
        body=body or event()
        raw=raw if raw is not None else json.dumps(body).encode()
        return self.client.post('/webhooks/paypal/'+(destination or 'paypal_'+self.workspace),content=raw,
                               headers=headers()|{'Content-Type':'application/json'})

    def row(self):
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT o.* FROM observations o JOIN evidence_heads h USING(workspace_id,purchase_id) WHERE o.observation_id=h.observation_id AND o.generation=h.generation AND o.purchase_id=%s',(self.purchase,))
            return cursor.fetchone()

    def test_complete_payment_investigation_is_current_and_cannot_propose_repair(self):
        self.register(); collect(self.app,claim(self.db,self.workspace))
        row=self.row(); facts=row['facts']
        self.assertTrue(facts['payment_complete'] and facts['access_complete'])
        self.assertFalse(facts['reversal_complete'] or facts['financial_complete'] or facts['capabilities']['access_repair'])
        self.assertEqual(facts['payments'][0]['capture_id'],CAPTURE)
        self.assertNotIn('payment_intent_id',facts['payments'][0])
        login=self.client.post('/dev/sessions/owner_a',headers={'X-Demo-Login-Key':self.app.state.settings.demo_login_key}).json()
        listing=self.client.get(f'/api/workspaces/{self.workspace}/cases').json()['data']
        case=listing[0]
        self.assertTrue(case['evidence_fresh']); self.assertEqual(case['current_outcome'],'manual_review')
        self.assertIn('paid_access_missing',case['current_reasons'])
        base=f'/api/workspaces/{self.workspace}/cases/'+case['case_id']
        detail=self.client.get(base).json(); self.assertEqual(detail['provider'],'paypal')
        denied=self.client.post(base+'/proposals',headers={'X-CSRF-Token':login['csrf_token']},json={
            'reason':'Verify access repair','observation_id':case['latest_observation_id'],'fingerprint':case['fingerprint']})
        self.assertEqual(denied.status_code,409)
        check=self.client.post(base+'/check',headers={'X-CSRF-Token':login['csrf_token']})
        self.assertEqual(check.status_code,202)
        self.assertEqual(self.client.get(base+'/checks/'+check.json()['job_id']).status_code,200)
        self.assertEqual(self.client.post(base+'/check',headers={'X-CSRF-Token':login['csrf_token']}).status_code,429)
        # Background sweeps coalesce without dirtying the foreground check.
        schedule_page(self.db,self.workspace,'paypal_'+self.workspace,force=True)
        self.assertTrue(all(req.method=='GET' or req.url.path=='/v1/oauth2/token' for req in self.calls))

    def test_bindings_are_immutable_and_cross_workspace_registration_is_rejected(self):
        self.register()
        auth=self.registration_headers()
        self.assertEqual(self.client.post('/api/purchases',headers=self.registration_headers(self.other),json=self.registration).status_code,403)
        self.assertEqual(self.client.post(f'/api/purchases/{self.purchase}/payment-attempts',headers=auth,json={'payment_intent_id':CAPTURE}).status_code,409)
        second=self.purchase+'_other'
        self.assertEqual(self.client.post('/api/purchases',headers=auth,json=self.registration|{'purchase_id':second}).status_code,200)
        self.assertEqual(self.client.post(f'/api/purchases/{second}/paypal-orders',headers=auth,json={'order_id':ORDER}).status_code,409)
        self.assertEqual(self.client.post(f'/api/purchases/{second}/paypal-captures',headers=auth,json={'order_id':ORDER,'capture_id':CAPTURE}).status_code,409)
        with self.db.transaction(self.other) as cursor:
            cursor.execute('SELECT count(*) AS count FROM paypal_orders'); self.assertEqual(cursor.fetchone()['count'],0)
            cursor.execute('SELECT count(*) AS count FROM jobs'); self.assertEqual(cursor.fetchone()['count'],0)

    def test_verified_duplicates_coalesce_and_conflicting_payload_is_rejected(self):
        self.register()
        self.assertEqual(self.send().status_code,200)
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(lambda _:self.send(),range(3)))
        self.assertTrue(all(response.status_code==200 and response.json()['duplicate'] for response in responses))
        self.assertEqual(self.send(event()|{'summary':'changed payload'}).status_code,409)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT count(*) AS count FROM inbox'); self.assertEqual(cursor.fetchone()['count'],1)
            cursor.execute('SELECT request_seq,payment_intent_id,purchase_id FROM jobs'); row=cursor.fetchone()
            self.assertEqual(row['request_seq'],3); self.assertIsNone(row['payment_intent_id']); self.assertEqual(row['purchase_id'],self.purchase)

    def test_signature_rejection_and_verifier_outage_never_acknowledge_receipt(self):
        for mode,status in (('bad_signature',400),('verification_unavailable',503)):
            self.mode=mode; self.assertEqual(self.send().status_code,status)
        self.assertEqual(self.send(raw=b'x'*(1024*1024+1)).status_code,413)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT count(*) AS count FROM inbox'); self.assertEqual(cursor.fetchone()['count'],0)
            cursor.execute('SELECT count(*) AS count FROM jobs'); self.assertEqual(cursor.fetchone()['count'],0)

    def test_receipt_and_job_roll_back_together_before_commit(self):
        self.register()
        raw=json.dumps(event()).encode(); parsed=parse_event(raw)
        @contextmanager
        def broken_transaction(workspace):
            with self.db.transaction(workspace) as cursor:
                yield cursor
                raise psycopg2.OperationalError('Injected pre-commit failure')
        with self.assertRaises(psycopg2.OperationalError):
            persist(SimpleNamespace(transaction=broken_transaction),self.workspace,'paypal_'+self.workspace,raw,*parsed)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT count(*) AS count FROM inbox'); self.assertEqual(cursor.fetchone()['count'],0)
            cursor.execute('SELECT request_seq FROM jobs'); self.assertEqual(cursor.fetchone()['request_seq'],2)

    def test_wrong_buyer_or_unregistered_capture_is_incomplete_not_empty_success(self):
        self.register(with_capture=False)
        job=claim(self.db,self.workspace)
        with self.assertRaises(ReadFailure) as caught: collect(self.app,job)
        self.assertEqual(caught.exception.code,'paypal_capture_coverage_changed')
        self.assertFalse(self.row()['facts']['payment_complete']); fail(self.db,job,caught.exception)
        self.assertEqual(self.client.post(f'/api/purchases/{self.purchase}/paypal-captures',headers=self.registration_headers(),
            json={'order_id':ORDER,'capture_id':CAPTURE}).status_code,200)
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute("UPDATE jobs SET due_at=now() WHERE purchase_id=%s",(self.purchase,))
        self.mode='wrong_buyer'; job=claim(self.db,self.workspace)
        with self.assertRaises(ReadFailure) as caught: collect(self.app,job)
        self.assertFalse(caught.exception.retryable); self.assertFalse(self.row()['facts']['payment_complete'])

    def test_changed_order_and_expired_lease_cannot_publish_complete_records(self):
        self.register(); self.mode='changed_order'; job=claim(self.db,self.workspace)
        with self.assertRaises(ReadFailure) as caught: collect(self.app,job)
        self.assertEqual(caught.exception.code,'paypal_order_changed'); self.assertFalse(self.row()['facts']['payment_complete'])
        fail(self.db,job,caught.exception)
        with self.db.transaction(self.workspace) as cursor: cursor.execute("UPDATE jobs SET due_at=now() WHERE purchase_id=%s",(self.purchase,))
        self.mode='expired_lease'; job=claim(self.db,self.workspace)
        with self.assertRaises(ReadFailure) as caught: collect(self.app,job)
        self.assertEqual(caught.exception.code,'lease_lost')
        # A fresh worker can reclaim the same durable subject and recover.
        self.mode='normal'; replacement=claim(self.db,self.workspace)
        collect(self.app,replacement); self.assertTrue(self.row()['facts']['payment_complete'])

    def test_old_event_cannot_overwrite_current_provider_capture_status(self):
        self.register()
        self.orders['purchase_units'][0]['payments']['captures'][0]['status']='REFUNDED'
        self.capture['status']='REFUNDED'
        self.assertEqual(self.send().status_code,200)  # event snapshot says COMPLETED
        collect(self.app,claim(self.db,self.workspace))
        self.assertEqual(self.row()['facts']['payments'][0]['status'],'REFUNDED')
        with self.db.transaction(self.workspace) as cursor:
            cursor.execute('SELECT outcome,reasons FROM evaluations'); row=cursor.fetchone()
            self.assertEqual(row['outcome'],'manual_review'); self.assertIn('capture_reversal_reported',row['reasons'])


class PayPalReferenceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=local_environment(); cls.scratch=create_scratch(cls.env)
        cls.addClassCleanup(cls.drop_scratch)
        with psycopg2.connect(admin_url(cls.env,'postgres')) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO reference_runtime').format(sql.Identifier(cls.scratch)))
        migrate('reference',admin_url(cls.env,cls.scratch))

    drop_scratch=classmethod(PayPalDatabaseContracts.drop_scratch.__func__)

    def test_reference_target_is_typed_immutable_inactive_and_not_simulator_checkout(self):
        keys={'ws_a':{purpose:secrets.token_hex(32) for purpose in ('registration','adapter','provider','checkout')}}
        settings=Settings('reference',f"postgresql://reference_runtime:{self.env['REFERENCE_DB_PASSWORD']}@127.0.0.1:{self.env.get('POSTGRES_PORT','15432')}/{self.scratch}",
                          '',keys)
        app=create_app('reference',settings)
        with TestClient(app) as client:
            auth={'Authorization':'Bearer '+keys['ws_a']['checkout']}
            body={'purchase_id':'p_target','customer_id':'c_target','order_id':ORDER}
            for _ in range(2): self.assertEqual(client.post('/demo/paypal-targets',headers=auth,json=body).status_code,200)
            self.assertEqual(client.post('/demo/paypal-targets',headers=auth,json=body|{'order_id':'OTHERORDER123456'}).status_code,409)
            self.assertEqual(client.post('/demo/checkouts/p_target/pay',headers=auth).status_code,409)
            access=client.get('/internal/access/p_target',headers={'Authorization':'Bearer '+keys['ws_a']['adapter']})
            self.assertEqual(access.json()['status'],'inactive')
            with app.state.database.transaction('ws_a') as cursor:
                cursor.execute('SELECT payment_intent_id,paypal_order_id FROM orders'); row=cursor.fetchone()
                self.assertIsNone(row['payment_intent_id']); self.assertEqual(row['paypal_order_id'],ORDER)
                cursor.execute('SELECT count(*) AS count FROM registration_outbox'); self.assertEqual(cursor.fetchone()['count'],0)


if __name__=='__main__': unittest.main(verbosity=2)
