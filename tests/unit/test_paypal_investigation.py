"""Order/buyer/coverage and authenticated delivery contracts, with no network."""
import copy
from datetime import UTC,datetime,timedelta
import json
import os
import unittest
from unittest.mock import patch

import httpx
from starlette.datastructures import Headers

from backend.app.cases import present
from backend.app.jobs import ReadFailure
from backend.app.paypal_provider import PayPalSandboxClient,PayPalSandboxConnection,connections_from_env
from backend.app.paypal_investigation import normalize_order,decision_for,POLICY
from backend.app.paypal_ingestion import parse_event,verification_payload
from backend.app.detection.projection import material_fingerprint
from backend.app.repairs import eligible

ORDER='25M43554V9523650M'; CAPTURE='74L756601X447022Y'
SELLER='YXZY75W2GKDQE'; BUYER='QYR5Z8XDVJNXQ'; WEBHOOK='8EH63422U4696331R'


def purchase():
    return {'workspace_id':'ws_a','purchase_id':'p_fixture','customer_id':'c_fixture','product_id':'digital_pass',
            'provider_customer_id':BUYER,'connection_id':'paypal_ws_a','expected_amount_minor':2500,'currency':'usd'}


def order():
    return {'id':ORDER,'intent':'CAPTURE','status':'COMPLETED','payer':{'payer_id':BUYER,'email_address':'omit@example.invalid'},
        'purchase_units':[{'payee':{'merchant_id':SELLER},'amount':{'currency_code':'USD','value':'25.00'},
            'payments':{'captures':[{'id':CAPTURE,'status':'COMPLETED','amount':{'currency_code':'USD','value':'25.00'}}]}}]}


def capture():
    return {'id':CAPTURE,'status':'COMPLETED','amount':{'currency_code':'USD','value':'25.00'},
        'payee':{'merchant_id':SELLER},'supplementary_data':{'related_ids':{'order_id':ORDER}},
        'create_time':'2024-10-23T20:55:19Z','update_time':'2024-10-23T20:55:19Z'}


def event():
    return {'id':'WH-TEST-EVENT','event_type':'PAYMENT.CAPTURE.COMPLETED','resource_type':'capture',
            'resource_version':'2.0','create_time':'2024-10-23T20:55:19Z','resource':capture()}


def headers():
    return {'paypal-auth-algo':'SHA256withRSA','paypal-cert-url':'https://api.sandbox.paypal.com/v1/notifications/certs/CERT-fixture',
        'paypal-transmission-id':'transmission-fixture','paypal-transmission-sig':'Zml4dHVyZQ==',
        'paypal-transmission-time':'2024-10-23T20:55:19Z'}


class PayPalInvestigationTests(unittest.TestCase):
    def test_order_binds_exact_buyer_and_seller_and_strips_personal_data(self):
        fact=normalize_order(order(),ORDER,purchase(),SELLER)
        self.assertEqual(fact['buyer_id'],BUYER)
        self.assertEqual(fact['captures'][0]['capture_id'],CAPTURE)
        self.assertNotIn('email_address',json.dumps(fact))
        for field in ('buyer','seller','order','custom_id','extra_unit','authorize'):
            body=order()
            if field=='buyer': body['payer']['payer_id']='FOREIGNBUYER1'
            if field=='seller': body['purchase_units'][0]['payee']['merchant_id']='FOREIGNSELLER'
            if field=='order': body['id']='FOREIGNORDER12345'
            if field=='custom_id': body['purchase_units'][0]['custom_id']='other_purchase'
            if field=='extra_unit': body['purchase_units'].append(copy.deepcopy(body['purchase_units'][0]))
            if field=='authorize': body['intent']='AUTHORIZE'
            with self.subTest(field=field),self.assertRaises(ReadFailure): normalize_order(body,ORDER,purchase(),SELLER)

    def test_buyer_sources_must_agree_and_missing_buyer_is_not_inferred(self):
        body=order(); body['payment_source']={'paypal':{'account_id':'FOREIGNBUYER1'}}
        with self.assertRaises(ReadFailure): normalize_order(body,ORDER,purchase(),SELLER)
        body=order(); del body['payer']
        with self.assertRaises(ReadFailure) as caught: normalize_order(body,ORDER,purchase(),SELLER)
        self.assertEqual(caught.exception.code,'paypal_buyer_unconfirmed')
        body['payment_source']={'paypal':{'account_id':BUYER}}
        self.assertEqual(normalize_order(body,ORDER,purchase(),SELLER)['buyer_id'],BUYER)

    def test_approved_order_without_capture_does_not_become_success(self):
        body=order(); body['status']='APPROVED'; body['purchase_units'][0]['payments']={}
        fact=normalize_order(body,ORDER,purchase(),SELLER)
        self.assertEqual(fact['status'],'APPROVED'); self.assertEqual(fact['captures'],[])

    def test_duplicate_capture_bad_amount_and_card_source_fail_closed(self):
        for kind in ('duplicate','float','unknown_status','card','currency'):
            body=order(); rows=body['purchase_units'][0]['payments']['captures']
            if kind=='duplicate': rows.append(rows[0].copy())
            if kind=='float': rows[0]['amount']['value']=25.0
            if kind=='unknown_status': rows[0]['status']='AUTHORIZED'
            if kind=='card': body.pop('payer'); body['payment_source']={'card':{'id':'not-a-buyer'}}
            if kind=='currency': rows[0]['amount']['currency_code']='JPY'
            with self.subTest(kind=kind),self.assertRaises(ReadFailure): normalize_order(body,ORDER,purchase(),SELLER)

    def facts(self):
        now=datetime.now(UTC)
        window={'started_at':now.isoformat(),'finished_at':now.isoformat(),'complete':True}
        return {'provider':'paypal','scope':{'workspace_id':'ws_a','connection_id':'paypal_ws_a','account_id':SELLER,'environment':'test'},
            'payment_complete':True,'access_complete':True,'reversal_complete':False,
            'windows':{'payment':window.copy(),'access':window.copy(),'reversal':window|{'complete':False}},
            'payments':[{'capture_id':CAPTURE,'status':'COMPLETED','amount_minor':2500,'currency':'usd'}],
            'access':{'status':'inactive'},'refunds':[],'disputes':[]}

    def test_paypal_policy_cannot_enable_repair_even_with_complete_flags(self):
        facts=self.facts(); facts['reversal_complete']=True
        result=decision_for(purchase(),facts,{'account_id':SELLER},datetime.now(UTC))
        self.assertEqual(result.outcome,'manual_review'); self.assertEqual(result.policy_version,POLICY)
        self.assertIn('paid_access_missing',result.reasons)
        self.assertIn('paypal_reversal_coverage_unknown',result.reasons)
        self.assertFalse(eligible({'discrepancy_code':'PAID_ACCESS_MISSING','state':'open',
            'policy_version':POLICY,'outcome':'eligible'}))

    def test_refunded_multiple_and_pending_capture_scenarios_are_distinct(self):
        for status,expected in (('REFUNDED','capture_reversal_reported'),('PARTIALLY_REFUNDED','capture_reversal_reported'),
                                ('PENDING','payment_capture_not_confirmed')):
            facts=self.facts(); facts['payments'][0]['status']=status
            self.assertIn(expected,decision_for(purchase(),facts,{'account_id':SELLER},datetime.now(UTC)).reasons)
        facts=self.facts(); facts['payments'].append(facts['payments'][0]|{'capture_id':'OTHERCAPTURE1234'})
        self.assertIn('multiple_captures_need_review',decision_for(purchase(),facts,{'account_id':SELLER},datetime.now(UTC)).reasons)

    def test_unknown_reversal_coverage_is_displayed_as_current_investigation_only(self):
        facts=self.facts()
        row={'provider':'paypal','windows':facts['windows'],'is_current':True,'outcome':'manual_review',
            'reasons':['paypal_reversal_coverage_unknown']}
        self.assertTrue(present(row)['evidence_fresh'])
        row['windows']['payment']['started_at']=(datetime.now(UTC)-timedelta(seconds=61)).isoformat()
        self.assertFalse(present(row)['evidence_fresh'])

    def test_fingerprint_tracks_order_binding_and_coverage(self):
        facts=self.facts(); before=material_fingerprint(facts)
        facts['registered_resources']={'orders':[ORDER],'captures':[]}
        self.assertNotEqual(before,material_fingerprint(facts))

    def test_configuration_rejects_partial_live_or_shared_sellers(self):
        env={'PAYPAL_ENABLED':'1','PAYPAL_ENVIRONMENT':'sandbox','PAYPAL_WORKSPACE_A_CLIENT_ID':'fixture-client-id',
            'PAYPAL_WORKSPACE_A_CLIENT_SECRET':'fixture-client-secret','PAYPAL_WORKSPACE_A_MERCHANT_ID':SELLER,
            'PAYPAL_WORKSPACE_A_WEBHOOK_ID':WEBHOOK}
        with patch.dict(os.environ,env,clear=True): self.assertEqual(set(connections_from_env()),{'ws_a'})
        for changes in ({'PAYPAL_ENVIRONMENT':'live'},{'PAYPAL_WORKSPACE_A_CLIENT_SECRET':''},{'PAYPAL_ENABLED':'yes'},
                        {key.replace('_A_','_B_'):value for key,value in env.items() if '_A_' in key}):
            with self.subTest(keys=list(changes)),patch.dict(os.environ,env|changes,clear=True),self.assertRaises(ValueError):
                connections_from_env()

    def test_invoice_only_connections_do_not_require_webhook_destinations(self):
        env={'PAYPAL_ENABLED':'1','PAYPAL_ENVIRONMENT':'sandbox',
            'PAYPAL_WORKSPACE_A_CLIENT_ID':'fixture-client-id', 'PAYPAL_WORKSPACE_A_CLIENT_SECRET':'fixture-client-secret',
            'PAYPAL_WORKSPACE_A_MERCHANT_ID':SELLER, 'PAYPAL_WORKSPACE_A_WEBHOOK_ID':'',
            'PAYPAL_WORKSPACE_B_CLIENT_ID':'other-client-id', 'PAYPAL_WORKSPACE_B_CLIENT_SECRET':'other-client-secret',
            'PAYPAL_WORKSPACE_B_MERCHANT_ID':'ABCDE12345678'}
        with patch.dict(os.environ,env,clear=True):
            configured=connections_from_env()
            self.assertEqual(set(configured),{'ws_a','ws_b'})
            self.assertTrue(all(item.webhook_id is None for item in configured.values()))
        with patch.dict(os.environ,env|{'PAYPAL_WORKSPACE_B_CLIENT_ID':'fixture-client-id'},clear=True),self.assertRaises(ValueError):
            connections_from_env()

    def test_invoice_only_webhook_route_is_disabled_before_body_or_verification(self):
        import asyncio
        from types import SimpleNamespace
        from fastapi import HTTPException
        from backend.app.paypal_ingestion import receive
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(
            paypal={'ws_a':PayPalSandboxConnection('fixture-client-id','fixture-client-secret',SELLER)}))))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(receive('paypal_ws_a',request))
        self.assertEqual(caught.exception.status_code,404)

    def test_verification_payload_rejects_duplicates_arbitrary_urls_and_missing_destination(self):
        valid=verification_payload(event(),Headers(headers()),WEBHOOK)
        self.assertEqual(valid['webhook_id'],WEBHOOK)
        for changes in ({'paypal-cert-url':'https://evil.example/cert'}, {'paypal-cert-url':'https://api.sandbox.paypal.com@evil.example/cert'},
                        {'paypal-auth-algo':'none'},{'paypal-transmission-time':'2024-01-01'},{'paypal-transmission-sig':'bad\r\nheader'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError): verification_payload(event(),Headers(headers()|changes),WEBHOOK)
        raw=Headers(headers()).raw+[(b'paypal-transmission-id',b'second')]
        with self.assertRaises(ValueError): verification_payload(event(),Headers(raw=raw),WEBHOOK)
        with self.assertRaises(ValueError): verification_payload(event(),Headers(headers()),None)

    def test_remote_verification_requires_exact_success_not_just_http_ok(self):
        cfg=PayPalSandboxConnection('fixture-client-id','fixture-client-secret',SELLER,webhook_id=WEBHOOK)
        for status in ('SUCCESS','FAILURE',None,True):
            requests=[]
            def handle(req):
                requests.append(req)
                return httpx.Response(200,json={'access_token':'fixture-token','token_type':'Bearer','expires_in':3600}
                    if req.url.path=='/v1/oauth2/token' else {'verification_status':status})
            with httpx.Client(transport=httpx.MockTransport(handle)) as http:
                reader=PayPalSandboxClient(cfg,http)
                if status=='SUCCESS': reader.verify_webhook(event(),Headers(headers()))
                else:
                    with self.assertRaises(ValueError): reader.verify_webhook(event(),Headers(headers()))
            self.assertEqual([str(req.url.host) for req in requests],['api-m.sandbox.paypal.com']*2)
            self.assertEqual(json.loads(requests[-1].content)['webhook_id'],WEBHOOK)

    def test_event_versions_unknown_types_and_unbound_refunds_do_not_invent_identity(self):
        raw=lambda body:json.dumps(body).encode()
        self.assertEqual(parse_event(raw(event()))[1:4],('accepted','capture',CAPTURE))
        self.assertEqual(parse_event(raw(event()|{'resource_version':'3.0'}))[1],'quarantined')
        self.assertEqual(parse_event(raw(event()|{'event_type':'CUSTOMER.DISPUTE.CREATED'}))[1],'ignored')
        refund=event()|{'event_type':'PAYMENT.CAPTURE.REFUNDED','resource_type':'refund','resource':{'id':'REFUNDREFERENCE1'}}
        self.assertEqual(parse_event(raw(refund))[1],'quarantined')
        refund['resource']['supplementary_data']={'related_ids':{'capture_id':CAPTURE}}
        self.assertEqual(parse_event(raw(refund))[-1],CAPTURE)
        with self.assertRaises(ValueError): parse_event(b'{"id":"one","id":"two"}')


if __name__=='__main__': unittest.main()
