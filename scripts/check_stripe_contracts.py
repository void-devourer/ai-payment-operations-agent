"""Offline Stripe-contract fixtures against real PostgreSQL; never genuine Stripe proof."""

import copy
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
import time
import unittest
import uuid

import httpx
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import Settings,StripeConnection,STRIPE_API_VERSION
from backend.app.database import Database
from backend.app.evidence import collect
from backend.app.jobs import claim
from backend.app.main import create_app
from scripts.check_phase1 import local_environment


class StripeDatabaseContractTests(unittest.TestCase):
    def setUp(self):
        env=local_environment()
        self.workspace='ws_fixture_'+uuid.uuid4().hex
        self.purchase='p_'+uuid.uuid4().hex
        self.event_created=int(time.time())
        self.connection=StripeConnection('acct_fixture123','rk_'+'test_'+secrets.token_hex(16),'whsec_'+secrets.token_hex(16))
        self.keys={purpose:secrets.token_hex(32) for purpose in ('registration','provider','adapter','webhook')}
        settings=Settings('console',f"postgresql://console_runtime:{env['CONSOLE_DB_PASSWORD']}@127.0.0.1:{env.get('POSTGRES_PORT','15432')}/console",
            secrets.token_hex(32),{self.workspace:self.keys},stripe={self.workspace:self.connection})
        self.app=create_app('console',settings)
        self.client=TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.database=self.app.state.database
        self.registration={'workspace_id':self.workspace,'purchase_id':self.purchase,'customer_id':'customer_fixture',
            'product_id':'digital_pass','expected_amount_minor':2500,'currency':'usd',
            'connection_id':'stripe_'+self.workspace,'provider_customer_id':'cus_fixture'}
        self.payment={'id':'pi_fixture','object':'payment_intent','livemode':False,'status':'succeeded','amount_received':2500,
            'currency':'usd','customer':'cus_fixture','metadata':{'purchase_id':self.purchase},'latest_charge':'ch_fixture'}

    def register(self):
        headers={'Authorization':'Bearer '+self.keys['registration']}
        self.assertEqual(self.client.post('/api/purchases',json=self.registration,headers=headers).status_code,200)
        self.assertEqual(self.client.post('/api/purchases/'+self.purchase+'/payment-attempts',
            json={'payment_intent_id':'pi_fixture'},headers=headers).status_code,200)

    def send(self,**changes):
        event={'id':'evt_fixture','object':'event','type':'payment_intent.succeeded','created':self.event_created,
            'livemode':False,'api_version':STRIPE_API_VERSION,'data':{'object':self.payment},**changes}
        raw=json.dumps(event).encode()
        timestamp=str(int(time.time()))
        signature=hmac.new(self.connection.webhook_secret.encode(),timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.client.post('/webhooks/stripe/stripe_'+self.workspace,content=raw,
            headers={'Stripe-Signature':f't={timestamp},v1={signature}'})

    def test_signed_fixture_receipt_and_normalized_observation(self):
        self.register()
        self.assertEqual(self.send().status_code,200)
        self.assertTrue(self.send().json()['duplicate'])
        requests=[]
        def handle(request):
            requests.append(request)
            path=request.url.path
            values={'/v1/account':{'id':self.connection.account_id,'object':'account'},
                '/v1/payment_intents/pi_fixture':self.payment,
                '/v1/charges':{'object':'list','has_more':False,'data':[{'id':'ch_fixture','livemode':False,
                    'payment_intent':'pi_fixture','amount_refunded':0,'refunded':False,'disputed':False}]},
                '/v1/refunds':{'object':'list','has_more':False,'data':[]},
                '/v1/disputes':{'object':'list','has_more':False,'data':[]},
                '/internal/access/'+self.purchase:{'workspace_id':self.workspace,'purchase_id':self.purchase,
                    'customer_id':'customer_fixture','product_id':'digital_pass','status':'inactive','revision':0,'ever_activated':False,'complete':True}}
            return httpx.Response(200,json=values[path])
        with httpx.Client(transport=httpx.MockTransport(handle),trust_env=False) as client:
            original=self.app.state.http
            self.app.state.http=client
            try:
                collect(self.app,claim(self.database,self.workspace))
            finally:
                self.app.state.http=original
        with self.database.transaction(self.workspace) as cursor:
            cursor.execute('SELECT source,api_version,facts FROM observations WHERE purchase_id=%s',(self.purchase,))
            row=cursor.fetchone()
            self.assertEqual((row['source'],row['api_version']),('stripe_api_and_target',STRIPE_API_VERSION))
            self.assertTrue(all(row['facts'][bundle+'_complete'] for bundle in ('payment','reversal','access')))
            self.assertEqual(row['facts']['scope']['environment'],'test')
        self.assertTrue(all(request.method=='GET' for request in requests))

    def test_live_and_wrong_account_rejected_unsupported_version_quarantined(self):
        self.assertEqual(self.send(livemode=True).status_code,400)
        self.assertEqual(self.send(account='acct_other123').status_code,400)
        self.assertEqual(self.send(api_version='unsupported').json()['state'],'quarantined')
        with self.database.transaction(self.workspace) as cursor:
            cursor.execute('SELECT count(*) AS count FROM jobs')
            self.assertEqual(cursor.fetchone()['count'],0)

    def test_stripe_registration_cannot_select_another_connection(self):
        headers={'Authorization':'Bearer '+self.keys['registration']}
        self.assertEqual(self.client.post('/api/purchases',json=self.registration|{'connection_id':'stripe_ws_a'},headers=headers).status_code,403)

    def test_reference_test_target_does_not_generate_simulator_registration(self):
        env=local_environment()
        body={'purchase_id':'stripe_target_'+uuid.uuid4().hex,'customer_id':'c_'+uuid.uuid4().hex,'payment_intent_id':'pi_fixture'}
        headers={'Authorization':'Bearer '+env['WORKSPACE_A_CHECKOUT_KEY']}
        with httpx.Client(timeout=5,trust_env=False) as client:
            for _ in range(2):
                self.assertEqual(client.post('http://127.0.0.1:8001/demo/stripe-targets',json=body,headers=headers).status_code,200)
            self.assertEqual(client.post('http://127.0.0.1:8001/demo/stripe-targets',json=body|{'payment_intent_id':'pi_changed'},headers=headers).status_code,409)
            self.assertEqual(client.post('http://127.0.0.1:8001/demo/checkouts/'+body['purchase_id']+'/pay',headers=headers).status_code,409)
            access=client.get('http://127.0.0.1:8001/internal/access/'+body['purchase_id'],headers={'Authorization':'Bearer '+env['WORKSPACE_A_ADAPTER_KEY']})
            self.assertEqual(access.json()['status'],'inactive')
        database=Database(f"postgresql://reference_runtime:{env['REFERENCE_DB_PASSWORD']}@127.0.0.1:{env.get('POSTGRES_PORT','15432')}/reference")
        try:
            with database.transaction('ws_a') as cursor:
                cursor.execute('SELECT count(*) AS count FROM registration_outbox WHERE purchase_id=%s',(body['purchase_id'],))
                self.assertEqual(cursor.fetchone()['count'],0)
        finally:
            database.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
