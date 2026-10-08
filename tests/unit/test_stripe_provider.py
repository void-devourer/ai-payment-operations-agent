import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from backend.app.config import STRIPE_API_VERSION,StripeConnection,stripe_connections_from_env
from backend.app.evidence import Reader
from backend.app.jobs import ReadFailure
from backend.app.stripe_provider import StripeReader,parse_stripe_event


def connection():
    return StripeConnection('acct_fixture123','rk_'+'test_'+'x'*24,'whsec_'+'y'*24)


class FixtureReader:
    def __init__(self,changes=None):
        self.calls=[]
        self.values={
            '/v1/account':{'id':'acct_fixture123','object':'account'},
            '/v1/payment_intents/pi_1':{'id':'pi_1','object':'payment_intent','livemode':False,'status':'succeeded',
                'customer':'cus_1','amount_received':2500,'currency':'usd','latest_charge':'ch_1','metadata':{'purchase_id':'p_1'}},
            '/v1/charges':{'object':'list','has_more':False,'data':[{'id':'ch_1','livemode':False,'payment_intent':'pi_1',
                            'amount_refunded':0,'refunded':False,'disputed':False}]},
            '/v1/refunds':{'object':'list','has_more':False,'data':[]},
            '/v1/disputes':{'object':'list','has_more':False,'data':[]}}
        self.values.update(changes or {})

    def get(self,base,path,purpose,params=None):
        self.calls.append((base,path,purpose,params))
        value=self.values[path]
        return copy.deepcopy(value(params) if callable(value) else value)


class StripeContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture=FixtureReader()
        self.reader=StripeReader(self.fixture,connection())
        self.purchase={'purchase_id':'p_1','provider_customer_id':'cus_1'}

    def event(self,**changes):
        return {'id':'evt_1','object':'event','created':123,'livemode':False,'type':'payment_intent.succeeded',
                'api_version':STRIPE_API_VERSION,'data':{'object':self.fixture.values['/v1/payment_intents/pi_1']},**changes}

    def test_configuration_rejects_live_temporary_and_incomplete_keys(self):
        for key in ('sk_'+'live_'+'x'*24,'rkcs_'+'x'*24,'','rk_'+'test_'+'short'):
            with self.subTest(key_type=key[:8]),self.assertRaises(ValueError):
                StripeConnection('acct_fixture123',key,connection().webhook_secret)
        with patch.dict('os.environ',{'STRIPE_ENABLED':'1'},clear=True),self.assertRaises(ValueError):
            stripe_connections_from_env()
        self.assertNotIn(connection().read_key,repr(connection()))

    def test_account_and_version_are_verified(self):
        self.reader.verify_account()
        self.fixture.values['/v1/account']['id']='acct_wrong123'
        with self.assertRaises(ReadFailure):
            self.reader.verify_account()
        with self.assertRaises(ValueError):
            StripeConnection('acct_fixture123',connection().read_key,connection().webhook_secret,'unknown.version')

    def test_webhook_direct_account_and_refund_shape(self):
        self.assertEqual(parse_stripe_event(json.dumps(self.event()),connection())[2],'pi_1')
        refund={'id':'re_1','object':'refund','payment_intent':'pi_1'}
        self.assertEqual(parse_stripe_event(json.dumps(self.event(type='refund.updated',data={'object':refund})),connection())[2],'pi_1')

    def test_webhook_live_foreign_account_and_simulator_rejected(self):
        for changes in ({'livemode':True},{'account':'acct_other123'},{'context':'acct_other123'},
                        {'id':'sim_evt_1'},{'data':{'object':{'id':'pi_1','livemode':True}}}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                parse_stripe_event(json.dumps(self.event(**changes)),connection())

    def test_authentic_unsupported_version_is_quarantined(self):
        self.assertEqual(parse_stripe_event(json.dumps(self.event(api_version='unknown',data=[])),connection())[1],'quarantined')

    def test_payment_customer_metadata_money_and_live_scope(self):
        self.assertEqual(self.reader.payment(self.purchase,'pi_1')['status'],'succeeded')
        original=copy.deepcopy(self.fixture.values['/v1/payment_intents/pi_1'])
        for changes in ({'customer':'cus_wrong'},{'metadata':{'purchase_id':'other'}},{'amount_received':True},
                        {'livemode':True},{'latest_charge':None},{'currency':'USD'}):
            self.fixture.values['/v1/payment_intents/pi_1']=original|changes
            with self.subTest(changes=changes),self.assertRaises(ReadFailure):
                self.reader.payment(self.purchase,'pi_1')

    def test_manual_capture_is_not_payment_success(self):
        self.fixture.values['/v1/payment_intents/pi_1'].update(status='requires_capture',amount_received=0)
        result=self.reader.payment(self.purchase,'pi_1')
        self.assertEqual((result['status'],result['amount_received_minor']),('requires_capture',0))

    def test_success_reads_charges_refunds_and_disputes_independently(self):
        payment=self.reader.payment(self.purchase,'pi_1')
        self.assertEqual(self.reader.reversals(payment),([],[]))
        self.assertEqual([row[1] for row in self.fixture.calls],['/v1/payment_intents/pi_1','/v1/charges','/v1/refunds','/v1/disputes','/v1/payment_intents/pi_1'])

    def test_partial_refund_keeps_success_but_records_reversal(self):
        self.fixture.values['/v1/charges']['data'][0]['amount_refunded']=100
        self.fixture.values['/v1/refunds']['data']=[{'id':'re_1','payment_intent':'pi_1','charge':'ch_1','amount':100,'status':'succeeded'}]
        payment=self.reader.payment(self.purchase,'pi_1')
        refunds,_=self.reader.reversals(payment)
        self.assertEqual((payment['status'],refunds[0]['amount_minor']),('succeeded',100))

    def test_historical_dispute_and_pending_refund_are_retained(self):
        self.fixture.values['/v1/refunds']['data']=[{'id':'re_1','payment_intent':'pi_1','charge':'ch_1','amount':100,'status':'pending'}]
        self.fixture.values['/v1/disputes']['data']=[{'id':'du_1','payment_intent':'pi_1','charge':'ch_1','livemode':False,'status':'won'}]
        refunds,disputes=self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))
        self.assertEqual((refunds[0]['status'],disputes[0]['status']),('pending','won'))

    def test_pending_refund_total_does_not_hide_history_or_force_zero(self):
        self.fixture.values['/v1/charges']['data'][0]['amount_refunded']=100
        self.fixture.values['/v1/refunds']['data']=[{'id':'re_1','payment_intent':'pi_1','charge':'ch_1','amount':100,'status':'pending'}]
        refunds,_=self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))
        self.assertEqual(refunds[0]['status'],'pending')

    def test_paginated_refunds_complete_and_repeated_cursor_rejected(self):
        def pages(params):
            return {'object':'list','has_more':'starting_after' not in params,'data':[
                {'id':'re_2' if 'starting_after' in params else 're_1','payment_intent':'pi_1','charge':'ch_1','amount':1,'status':'pending'}]}
        self.fixture.values['/v1/refunds']=pages
        refunds,_=self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))
        self.assertEqual(len(refunds),2)
        self.fixture.values['/v1/refunds']=lambda _: {'object':'list','has_more':True,'data':[{'id':'re_1','payment_intent':'pi_1'}]}
        with self.assertRaises(ReadFailure):
            self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))

    def test_denied_or_failed_later_page_never_means_zero_refunds(self):
        def pages(params):
            if 'starting_after' in params:
                raise ReadFailure('permission_denied',False)
            return {'object':'list','has_more':True,'data':[{'id':'re_1','payment_intent':'pi_1'}]}
        self.fixture.values['/v1/refunds']=pages
        with self.assertRaises(ReadFailure) as raised:
            self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))
        self.assertFalse(raised.exception.retryable)

    def test_reversal_contradiction_is_retryable(self):
        self.fixture.values['/v1/charges']['data'][0]['amount_refunded']=100
        with self.assertRaises(ReadFailure) as raised:
            self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))
        self.assertEqual(raised.exception.code,'stripe_reversal_changed')
        self.assertTrue(raised.exception.retryable)

    def test_foreign_intent_in_reversal_page_is_rejected(self):
        self.fixture.values['/v1/disputes']['data']=[{'id':'du_1','payment_intent':'pi_other','charge':'ch_1','livemode':False,'status':'won'}]
        with self.assertRaises(ReadFailure):
            self.reader.reversals(self.reader.payment(self.purchase,'pi_1'))

    def test_http_transport_is_get_only_fixed_origin_and_version_pinned(self):
        requests=[]
        def handle(request):
            requests.append(request)
            return httpx.Response(200,json={'id':'acct_fixture123','object':'account'})
        with httpx.Client(transport=httpx.MockTransport(handle),trust_env=False) as client:
            app=SimpleNamespace(state=SimpleNamespace(database=None,http=client,
                                settings=SimpleNamespace(stripe={'ws_a':connection()})))
            reader=Reader(app,{'workspace_id':'ws_a','connection_id':'stripe_ws_a'})
            with patch('backend.app.evidence.heartbeat'),patch('backend.app.evidence.reserve_request',return_value=True):
                StripeReader(reader,connection()).verify_account()
                with self.assertRaises(ReadFailure):
                    reader.get('https://untrusted.example','/v1/account','stripe')
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0].method,'GET')
        self.assertEqual(requests[0].headers['Stripe-Version'],STRIPE_API_VERSION)
        self.assertNotIn(connection().read_key,str(requests[0].url))
