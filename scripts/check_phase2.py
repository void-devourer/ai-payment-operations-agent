"""Real PostgreSQL/HTTP Phase 2 failure checks; temporarily pauses local workers."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC,datetime,timedelta
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import httpx
import psycopg2

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_phase1 import local_environment
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.evidence import Reader,begin,collect,publish
from backend.app.ingestion import parse_event,persist_receipt
from backend.app.jobs import ReadFailure,claim,enqueue,fail,finish,heartbeat,reserve_request
from backend.app.main import create_app
from fastapi.testclient import TestClient

WORKERS=['console-worker','simulator-worker','reference-worker']


class Phase2IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env=local_environment()
        cls.http=httpx.Client(timeout=8,trust_env=False)
        port=cls.env.get('POSTGRES_PORT','15432')
        cls.runtime_url=f"postgresql://console_runtime:{cls.env['CONSOLE_DB_PASSWORD']}@127.0.0.1:{port}/console"
        cls.database=Database(cls.runtime_url)
        keys={f'ws_{letter.lower()}':{purpose.lower():cls.env[f'WORKSPACE_{letter}_{purpose}_KEY']
              for purpose in ('REGISTRATION','ADAPTER','PROVIDER','WEBHOOK')} for letter in ('A','B')}
        cls.settings=Settings('console','unused',cls.env['DEMO_LOGIN_KEY'],keys,
                              'http://127.0.0.1:8000','http://127.0.0.1:8002',reference_url='http://127.0.0.1:8001')
        cls.app=SimpleNamespace(state=SimpleNamespace(settings=cls.settings,database=cls.database,http=cls.http))

    @classmethod
    def tearDownClass(cls):
        cls.database.close()
        cls.http.close()

    def headers(self,purpose='PROVIDER',letter='A'):
        return {'Authorization':'Bearer '+self.env[f'WORKSPACE_{letter}_{purpose}_KEY']}

    def event(self,intent=None,**changes):
        return {'id':'sim_evt_'+uuid.uuid4().hex,'object':'event','api_version':'simulator.v1',
                'type':'payment_intent.succeeded','livemode':False,'created':int(time.time()),
                'account':'sim_acct_ws_a','data':{'object':{'id':intent or 'sim_pi_'+uuid.uuid4().hex}},**changes}

    def send(self,event,letter='A',timestamp=None,raw=None):
        raw=raw or json.dumps(event,sort_keys=True,separators=(',',':')).encode()
        timestamp=str(timestamp or int(time.time()))
        signature=hmac.new(self.env[f'WORKSPACE_{letter}_WEBHOOK_KEY'].encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.http.post(f'http://127.0.0.1:8000/webhooks/simulator/sim_ws_{letter.lower()}',content=raw,
                              headers={'Simulator-Signature':f't={timestamp},v1={signature}','Content-Type':'application/json'})

    def purchase(self,letter='A',paid=True):
        suffix=uuid.uuid4().hex
        body={'purchase_id':'p_'+suffix,'customer_id':'c_'+suffix,'fault_mode':'pause_fulfillment'}
        result=self.http.post('http://127.0.0.1:8001/demo/checkouts',json=body,headers=self.headers('CHECKOUT',letter))
        result.raise_for_status()
        intent=result.json()['payment_intent_id']
        self.http.post('http://127.0.0.1:8002/internal/payments',json={**{key:body[key] for key in ('purchase_id','customer_id')},
                         'amount_minor':2500,'currency':'usd'},headers=self.headers(letter=letter)).raise_for_status()
        if paid:
            self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/confirm',headers=self.headers(letter=letter)).raise_for_status()
        registration={**{key:body[key] for key in ('purchase_id','customer_id')},'workspace_id':f'ws_{letter.lower()}',
                      'product_id':'digital_pass','expected_amount_minor':2500,'currency':'usd',
                      'connection_id':f'sim_ws_{letter.lower()}','provider_customer_id':body['customer_id']}
        self.http.post('http://127.0.0.1:8000/api/purchases',json=registration,headers=self.headers('REGISTRATION',letter)).raise_for_status()
        self.http.post(f"http://127.0.0.1:8000/api/purchases/{body['purchase_id']}/payment-attempts",
                       json={'payment_intent_id':intent},headers=self.headers('REGISTRATION',letter)).raise_for_status()
        return body,intent

    def lease(self,intent,workspace='ws_a'):
        with self.database.transaction(workspace) as cursor:
            cursor.execute("""UPDATE jobs SET state='leased',lease_token=%s,lease_until=now()+interval '30 seconds',
                claimed_seq=request_seq,attempts=attempts+1 WHERE payment_intent_id=%s
                AND state IN ('queued','retry_wait') RETURNING *""", (uuid.uuid4().hex,intent))
            return dict(cursor.fetchone())

    def facts(self,purchase,workspace='ws_a'):
        with self.database.transaction(workspace) as cursor:
            cursor.execute("""SELECT o.* FROM evidence_heads h JOIN observations o USING(workspace_id,purchase_id)
                WHERE h.purchase_id=%s AND h.observation_id=o.observation_id""", (purchase,))
            return cursor.fetchone()

    def test_01_receipt_duplicate_conflict_quarantine_and_rejection(self):
        event=self.event()
        self.assertEqual(self.send(event).status_code,200)
        self.assertTrue(self.send(event).json()['duplicate'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses=list(pool.map(lambda _:self.send(event),range(4)))
        self.assertTrue(all(response.status_code==200 and response.json()['duplicate'] for response in responses))
        self.assertEqual(self.send(event|{'created':event['created']+1}).status_code,409)
        self.assertEqual(self.send(self.event(api_version='future.v2')).json()['state'],'quarantined')
        self.assertEqual(self.send(self.event(type='unhandled.type')).json()['state'],'ignored')
        self.assertEqual(self.send(self.event(livemode=True)).status_code,400)
        self.assertEqual(self.send(self.event(),timestamp=int(time.time())-301).status_code,400)
        self.assertEqual(self.send(self.event(),letter='B').status_code,400)
        self.assertEqual(self.send(self.event(),raw=b'x'*(1024*1024+1)).status_code,413)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS count FROM inbox WHERE event_id=%s',(event['id'],))
            self.assertEqual(cursor.fetchone()['count'],1)
            cursor.execute('SELECT request_seq FROM jobs WHERE payment_intent_id=%s',(event['data']['object']['id'],))
            self.assertEqual(cursor.fetchone()['request_seq'],1)

    def test_02_receipt_and_job_rollback_together(self):
        event=self.event()
        raw=json.dumps(event).encode()
        @contextmanager
        def fail_commit(workspace):
            with self.database.transaction(workspace) as cursor:
                yield cursor
                raise psycopg2.OperationalError('Injected pre-commit failure')
        broken=SimpleNamespace(transaction=fail_commit)
        with self.assertRaises(psycopg2.OperationalError):
            persist_receipt(broken,'ws_a','sim_ws_a',raw,event,'accepted',event['data']['object']['id'])
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS count FROM inbox WHERE event_id=%s',(event['id'],))
            self.assertEqual(cursor.fetchone()['count'],0)
            cursor.execute('SELECT count(*) AS count FROM jobs WHERE payment_intent_id=%s',(event['data']['object']['id'],))
            self.assertEqual(cursor.fetchone()['count'],0)
        self.assertEqual(self.send(event).status_code,200)
        # Exercise the HTTP acknowledgement boundary with the same real transaction failure.
        event=self.event()
        raw=json.dumps(event).encode()
        timestamp=str(int(time.time()))
        signature=hmac.new(self.env['WORKSPACE_A_WEBHOOK_KEY'].encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        settings=Settings('console',self.runtime_url,self.settings.demo_login_key,self.settings.keys,
                          self.settings.console_url,self.settings.simulator_url,reference_url=self.settings.reference_url)
        app=create_app('console',settings)
        with TestClient(app) as client:
            original=app.state.database
            app.state.database=broken
            response=client.post('/webhooks/simulator/sim_ws_a',content=raw,headers={'Simulator-Signature':f't={timestamp},v1={signature}'})
            self.assertEqual(response.status_code,503)
            app.state.database=original
            response=client.post('/webhooks/simulator/sim_ws_a',content=raw,headers={'Simulator-Signature':f't={timestamp},v1={signature}'})
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.json()['duplicate'])

    def test_03_current_reads_ignore_snapshot_and_preserve_history(self):
        body,intent=self.purchase()
        self.send(self.event(intent,data={'object':{'id':intent,'status':'failed','metadata':{'purchase_id':'wrong'}}})).raise_for_status()
        job=self.lease(intent)
        collect(self.app,job)
        observation=self.facts(body['purchase_id'])
        facts=observation['facts']
        self.assertEqual(facts['payments'][0]['status'],'succeeded')
        self.assertTrue(facts['payment_complete'] and facts['reversal_complete'] and facts['access_complete'])
        self.assertFalse(facts['financial_complete'])
        self.assertEqual(facts['access']['status'],'inactive')
        canonical=json.dumps(facts,sort_keys=True,separators=(',',':'))
        self.assertEqual(observation['content_digest'],hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(observation['source'],'simulator_api_and_target')

    def test_04_complete_refund_dispute_pagination_and_partial_failure(self):
        body,intent=self.purchase()
        for index in range(21):
            self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/refunds',headers=self.headers(),
                           json={'resource_id':f'refund_{index:03}','status':'pending','amount_minor':1}).raise_for_status()
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/disputes',headers=self.headers(),
                       json={'resource_id':'dispute_001','status':'won','amount_minor':2500}).raise_for_status()
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'page_fault':True}).raise_for_status()
        job=self.lease(intent)
        with self.assertRaises(ReadFailure) as raised:
            collect(self.app,job)
        self.assertTrue(fail(self.database,job,raised.exception))
        facts=self.facts(body['purchase_id'])['facts']
        self.assertTrue(facts['payment_complete'] and facts['access_complete'])
        self.assertFalse(facts['reversal_complete'])
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={}).raise_for_status()
        collect(self.app,self.lease(intent))
        facts=self.facts(body['purchase_id'])['facts']
        self.assertTrue(facts['reversal_complete'])
        self.assertEqual((len(facts['refunds']),len(facts['disputes'])),(21,1))

    def test_05_scope_and_evidence_rls_are_enforced(self):
        body,intent=self.purchase('B')
        collect(self.app,self.lease(intent,'ws_b'))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS count FROM observations WHERE purchase_id=%s',(body['purchase_id'],))
            self.assertEqual(cursor.fetchone()['count'],0)
        with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
            with self.database.transaction('ws_b') as cursor:
                cursor.execute("UPDATE observations SET facts='{}'")

    def test_06_expired_worker_cannot_heartbeat_publish_or_complete(self):
        body,intent=self.purchase()
        old=self.lease(intent)
        purchase,attempts,generation=begin(self.database,old)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE jobs SET lease_until=now()-interval '1 second' WHERE job_id=%s",(old['job_id'],))
        for action in (lambda:heartbeat(self.database,old),
                       lambda:publish(self.database,old,purchase,attempts,generation,{},datetime.now(UTC),datetime.now(UTC))):
            with self.assertRaises(ReadFailure):
                action()
        self.assertFalse(fail(self.database,old,ReadFailure('late')))
        with self.assertRaises(ReadFailure):
            with self.database.transaction('ws_a') as cursor:
                finish(cursor,old)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("UPDATE jobs SET due_at='1900-01-01' WHERE job_id=%s",(old['job_id'],))
        fresh=claim(self.database,'ws_a')
        self.assertEqual(fresh['job_id'],old['job_id'])
        self.assertNotEqual(fresh['lease_token'],old['lease_token'])
        collect(self.app,fresh)

    def test_07_event_during_read_reschedules_same_active_job(self):
        body,intent=self.purchase()
        job=self.lease(intent)
        self.send(self.event(intent)).raise_for_status()
        collect(self.app,job)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT state,job_id FROM jobs WHERE payment_intent_id=%s',(intent,))
            row=cursor.fetchone()
            self.assertEqual((row['state'],row['job_id']),('queued',job['job_id']))
        collect(self.app,self.lease(intent))

    def test_08_permissions_dead_job_and_audited_redrive(self):
        body,intent=self.purchase()
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'read_fault':403}).raise_for_status()
        job=self.lease(intent)
        with self.assertRaises(ReadFailure) as raised:
            collect(self.app,job)
        self.assertFalse(raised.exception.retryable)
        fail(self.database,job,raised.exception)
        with httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False) as client:
            login=client.post('/dev/sessions/owner_a',headers={'X-Demo-Login-Key':self.env['DEMO_LOGIN_KEY']}).json()
            path=f"/api/workspaces/ws_a/jobs/{job['job_id']}/redrive"
            self.assertEqual(client.post(path).status_code,403)
            self.assertEqual(client.get(f"/api/workspaces/ws_a/purchases/{body['purchase_id']}/evidence").status_code,200)
            self.assertEqual(client.get('/api/workspaces/ws_b/integration-health').status_code,403)
            self.assertEqual(client.post(path,headers={'X-CSRF-Token':login['csrf_token']}).json()['job_id'],job['job_id'])
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT count(*) AS count FROM job_audit WHERE job_id=%s',(job['job_id'],))
            self.assertEqual(cursor.fetchone()['count'],1)
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={}).raise_for_status()
        collect(self.app,self.lease(intent))

    def test_09_throttling_retries_and_connection_budget(self):
        body,intent=self.purchase()
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'read_fault':429}).raise_for_status()
        job=self.lease(intent)
        with self.assertRaises(ReadFailure) as raised:
            collect(self.app,job)
        self.assertEqual(raised.exception.code,'provider_throttled')
        fail(self.database,job,raised.exception)
        self.assertFalse(reserve_request(self.database,'ws_a','sim_ws_a'))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT state,last_error,due_at FROM jobs WHERE job_id=%s',(job['job_id'],))
            row=cursor.fetchone()
            self.assertEqual((row['state'],row['last_error']),('retry_wait','provider_throttled'))
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={}).raise_for_status()

    def test_10_missing_binding_is_retryable_then_registration_recovers(self):
        suffix=uuid.uuid4().hex
        body={'purchase_id':'early_'+suffix,'customer_id':'c_'+suffix,'fault_mode':'pause_fulfillment'}
        result=self.http.post('http://127.0.0.1:8001/demo/checkouts',json=body,headers=self.headers('CHECKOUT'))
        result.raise_for_status()
        intent=result.json()['payment_intent_id']
        self.http.post(f"http://127.0.0.1:8001/demo/checkouts/{body['purchase_id']}/pay",headers=self.headers('CHECKOUT')).raise_for_status()
        event=self.event(intent)
        self.send(event).raise_for_status()
        job=self.lease(intent)
        with self.assertRaises(ReadFailure) as raised:
            collect(self.app,job)
        self.assertEqual(raised.exception.code,'binding_not_registered')
        fail(self.database,job,raised.exception)
        registration={**{key:body[key] for key in ('purchase_id','customer_id')},'workspace_id':'ws_a',
                      'product_id':'digital_pass','expected_amount_minor':2500,'currency':'usd',
                      'connection_id':'sim_ws_a','provider_customer_id':body['customer_id']}
        self.http.post('http://127.0.0.1:8000/api/purchases',json=registration,headers=self.headers('REGISTRATION')).raise_for_status()
        self.http.post(f"http://127.0.0.1:8000/api/purchases/{body['purchase_id']}/payment-attempts",
                       json={'payment_intent_id':intent},headers=self.headers('REGISTRATION')).raise_for_status()
        collect(self.app,self.lease(intent))
        self.assertTrue(self.facts(body['purchase_id'])['facts']['payment_complete'])

    def test_11_all_attempts_and_manual_capture_are_not_success(self):
        body,intent=self.purchase(paid=False)
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',headers=self.headers(),json={'status':'requires_capture'}).raise_for_status()
        collect(self.app,self.lease(intent))
        facts=self.facts(body['purchase_id'])['facts']
        self.assertEqual((facts['payments'][0]['status'],facts['payments'][0]['amount_received_minor']),('requires_capture',0))
        other=self.http.post('http://127.0.0.1:8002/internal/payments',headers=self.headers(),
               json={'purchase_id':body['purchase_id'],'attempt_id':'second','customer_id':body['customer_id'],'amount_minor':2500,'currency':'usd'}).json()['payment_intent_id']
        self.http.post(f"http://127.0.0.1:8000/api/purchases/{body['purchase_id']}/payment-attempts",
                       json={'payment_intent_id':other},headers=self.headers('REGISTRATION')).raise_for_status()
        with self.database.transaction('ws_a') as cursor:
            job_id=enqueue(cursor,'ws_a','sim_ws_a',intent)
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{other}/confirm',headers=self.headers()).raise_for_status()
        collect(self.app,self.lease(intent))
        facts=self.facts(body['purchase_id'])['facts']
        self.assertEqual(len(facts['registered_attempts']),2)
        self.assertTrue(facts['payment_complete'])
        self.assertEqual({payment['status'] for payment in facts['payments']},{'requires_capture','succeeded'})
        self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/confirm',headers=self.headers()).raise_for_status()
        with self.database.transaction('ws_a') as cursor:
            enqueue(cursor,'ws_a','sim_ws_a',intent)
        collect(self.app,self.lease(intent))
        self.assertEqual(sum(payment['status']=='succeeded' for payment in self.facts(body['purchase_id'])['facts']['payments']),2)

    def test_12_new_generation_rejects_an_older_response(self):
        body,intent=self.purchase()
        job=self.lease(intent)
        purchase,attempts,old_generation=begin(self.database,job)
        _,_,new_generation=begin(self.database,job)
        self.assertGreater(new_generation,old_generation)
        with self.assertRaises(ReadFailure) as raised:
            publish(self.database,job,purchase,attempts,old_generation,{},datetime.now(UTC),datetime.now(UTC))
        self.assertEqual(raised.exception.code,'observation_superseded')
        fail(self.database,job,ReadFailure('test_finished',False))

    def test_13_concurrent_claims_and_workspace_fairness(self):
        intents=['sim_pi_'+uuid.uuid4().hex for _ in range(2)]
        for intent in intents:
            with self.database.transaction('ws_b') as cursor:
                job_id=enqueue(cursor,'ws_b','sim_ws_b',intent)
                cursor.execute("UPDATE jobs SET due_at='1900-01-01' WHERE job_id=%s",(job_id,))
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=list(pool.map(lambda _:claim(self.database,'ws_b'),range(2)))
        self.assertEqual({job['payment_intent_id'] for job in jobs},set(intents))
        self.assertEqual(len({job['lease_token'] for job in jobs}),2)
        for job in jobs:
            fail(self.database,job,ReadFailure('test_finished',False))
        # A separate workspace claim never consumes workspace B's jobs.
        with self.database.transaction('ws_a') as cursor:
            intent='sim_pi_'+uuid.uuid4().hex
            job_id=enqueue(cursor,'ws_a','sim_ws_a',intent)
            cursor.execute("UPDATE jobs SET due_at='1899-01-01' WHERE job_id=%s",(job_id,))
        job=claim(self.database,'ws_a')
        self.assertEqual(job['payment_intent_id'],intent)
        fail(self.database,job,ReadFailure('test_finished',False))

    def test_14_mismatched_registered_attempt_remains_incomplete(self):
        body,intent=self.purchase()
        other=self.http.post('http://127.0.0.1:8002/internal/payments',headers=self.headers(),
               json={'purchase_id':'other_'+uuid.uuid4().hex,'customer_id':body['customer_id'],'amount_minor':2500,'currency':'usd'}).json()['payment_intent_id']
        self.http.post(f"http://127.0.0.1:8000/api/purchases/{body['purchase_id']}/payment-attempts",
                       json={'payment_intent_id':other},headers=self.headers('REGISTRATION')).raise_for_status()
        job=self.lease(intent)
        with self.assertRaises(ReadFailure) as raised:
            collect(self.app,job)
        self.assertFalse(raised.exception.retryable)
        self.assertFalse(self.facts(body['purchase_id'])['facts']['payment_complete'])
        fail(self.database,job,raised.exception)

    def test_15_retry_limit_retains_a_visible_dead_job(self):
        body,intent=self.purchase()
        job=self.lease(intent)
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('UPDATE jobs SET attempts=8 WHERE job_id=%s',(job['job_id'],))
        job['attempts']=8
        self.assertTrue(fail(self.database,job,ReadFailure('upstream_unavailable')))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT state,last_error FROM jobs WHERE job_id=%s',(job['job_id'],))
            self.assertEqual(dict(cursor.fetchone()),{'state':'dead','last_error':'upstream_unavailable'})

    def test_16_reversal_arriving_between_reads_is_retryable(self):
        body,intent=self.purchase()
        job=self.lease(intent)
        original=Reader.get
        inserted=False
        def changing_read(reader,base,path,purpose,params=None):
            nonlocal inserted
            if path.endswith('/refunds') and not inserted:
                self.http.post(f'http://127.0.0.1:8002/internal/payments/{intent}/refunds',headers=self.headers(),
                    json={'resource_id':'concurrent_refund','status':'pending','amount_minor':1}).raise_for_status()
                inserted=True
            return original(reader,base,path,purpose,params)
        with patch.object(Reader,'get',changing_read):
            with self.assertRaises(ReadFailure) as raised:
                collect(self.app,job)
        self.assertEqual(raised.exception.code,'reversal_changed')
        self.assertTrue(raised.exception.retryable)
        fail(self.database,job,raised.exception)
        self.assertFalse(self.facts(body['purchase_id'])['facts']['reversal_complete'])
        collect(self.app,self.lease(intent))
        facts=self.facts(body['purchase_id'])['facts']
        self.assertTrue(facts['reversal_complete'])
        self.assertEqual(len(facts['refunds']),1)


def automatic_delivery_check():
    env=local_environment()
    suffix=uuid.uuid4().hex
    headers={'Authorization':'Bearer '+env['WORKSPACE_B_CHECKOUT_KEY']}
    body={'purchase_id':'auto_'+suffix,'customer_id':'c_'+suffix,'fault_mode':'pause_fulfillment'}
    with httpx.Client(timeout=10,trust_env=False) as client:
        client.post('http://127.0.0.1:8001/demo/checkouts',json=body,headers=headers).raise_for_status()
        client.post(f"http://127.0.0.1:8001/demo/checkouts/{body['purchase_id']}/pay",headers=headers).raise_for_status()
        login=client.post('http://127.0.0.1:8000/dev/sessions/owner_b',headers={'X-Demo-Login-Key':env['DEMO_LOGIN_KEY']})
        login.raise_for_status()
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            response=client.get(f"http://127.0.0.1:8000/api/workspaces/ws_b/purchases/{body['purchase_id']}/evidence")
            if response.status_code==200 and response.json()['facts']['payment_complete'] and response.json()['facts']['reversal_complete']:
                print('Automatic webhook delivery and background evidence collection passed.')
                return
            time.sleep(.5)
        raise RuntimeError('Automatic webhook/evidence recovery did not complete within the test bound')


if __name__=='__main__':
    subprocess.run(['docker','compose','stop',*WORKERS],cwd=ROOT,check=True,capture_output=True)
    try:
        result=unittest.main(verbosity=2,exit=False).result
    finally:
        subprocess.run(['docker','compose','start',*WORKERS],cwd=ROOT,check=True,capture_output=True)
    if not result.wasSuccessful():
        sys.exit(1)
    automatic_delivery_check()
