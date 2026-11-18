"""Offline PayPal sandbox contract tests; never proof of real account acceptance."""
import unittest

import httpx

from backend.app.jobs import ReadFailure
from backend.app.paypal_provider import (
    API_BASE, PayPalSandboxClient, PayPalSandboxConnection, normalize_capture,
)

CAPTURE='74L756601X447022Y'
ORDER='25M43554V9523650M'
MERCHANT='YXZY75W2GKDQE'


def connection():
    return PayPalSandboxConnection('fixture-client-id', 'fixture-client-secret', MERCHANT)


def capture():
    return {'id':CAPTURE,'status':'COMPLETED','amount':{'currency_code':'USD','value':'25.00'},
            'supplementary_data':{'related_ids':{'order_id':ORDER}},
            'payee':{'merchant_id':MERCHANT,'email_address':'omit@example.invalid'},
            'create_time':'2024-10-23T20:55:19Z','update_time':'2024-10-23T20:55:19Z',
            'links':[{'rel':'refund','href':'https://untrusted.example/refund','method':'POST'}]}


class PayPalSandboxContractTests(unittest.TestCase):
    def client(self, handler, clock=lambda:100):
        http=httpx.Client(transport=httpx.MockTransport(handler),trust_env=False)
        self.addCleanup(http.close)
        return PayPalSandboxClient(connection(), http, clock=clock)

    def token(self):
        return {'access_token':'fixture-bearer-token','token_type':'Bearer','expires_in':3600}

    def test_completed_capture_is_exact_and_not_repair_or_settlement_evidence(self):
        fact=normalize_capture(capture(),CAPTURE,ORDER,MERCHANT)
        self.assertEqual(fact.amount_minor,2500)
        self.assertEqual(fact.currency,'usd')
        self.assertEqual(fact.order_id,ORDER)
        self.assertFalse(fact.reversals_complete)
        self.assertFalse(fact.settlement_verified)
        self.assertNotIn('email_address',repr(fact))

    def test_all_documented_statuses_remain_distinct(self):
        for status in ('COMPLETED','DECLINED','PARTIALLY_REFUNDED','PENDING','REFUNDED','FAILED'):
            with self.subTest(status=status):
                body=capture(); body['status']=status
                self.assertEqual(normalize_capture(body,CAPTURE,ORDER,MERCHANT).status,status)
        body=capture(); body['status']='APPROVED'
        with self.assertRaises(ReadFailure): normalize_capture(body,CAPTURE,ORDER,MERCHANT)

    def test_wrong_or_missing_capture_order_and_merchant_are_rejected(self):
        for field in ('capture','order','merchant','missing_merchant','missing_order'):
            with self.subTest(field=field):
                body=capture()
                if field=='capture': body['id']='9WRONGCAPTURE1234'
                if field=='order': body['supplementary_data']['related_ids']['order_id']='9WRONGORDER12345'
                if field=='merchant': body['payee']['merchant_id']='9WRONGMERCHAN'
                if field=='missing_merchant': del body['payee']
                if field=='missing_order': del body['supplementary_data']
                with self.assertRaises(ReadFailure): normalize_capture(body,CAPTURE,ORDER,MERCHANT)

    def test_money_is_decimal_and_usd_only(self):
        for value in (25.0,True,'NaN','Infinity','1e2','25.001','-25.00','0.00','1000000000000.01',' 25.00'):
            with self.subTest(value=value):
                body=capture(); body['amount']['value']=value
                with self.assertRaises(ReadFailure): normalize_capture(body,CAPTURE,ORDER,MERCHANT)
        for value,minor in [('25',2500),('25.0',2500),('0.01',1)]:
            body=capture(); body['amount']['value']=value
            self.assertEqual(normalize_capture(body,CAPTURE,ORDER,MERCHANT).amount_minor,minor)
        body=capture(); body['amount']['currency_code']='JPY'
        with self.assertRaises(ReadFailure): normalize_capture(body,CAPTURE,ORDER,MERCHANT)

    def test_invalid_timestamp_never_becomes_current_evidence(self):
        for created,updated in [('not-a-date','2024-10-23T20:55:19Z'),
                                ('2024-10-23T20:55:19','2024-10-23T20:55:19Z'),
                                ('2024-10-24T20:55:19Z','2024-10-23T20:55:19Z'),
                                ('2999-01-01T00:00:00Z','2999-01-01T00:00:00Z')]:
            body=capture(); body.update(create_time=created,update_time=updated)
            with self.assertRaises(ReadFailure): normalize_capture(body,CAPTURE,ORDER,MERCHANT)

    def test_live_configuration_and_secret_repr_are_rejected(self):
        with self.assertRaises(ValueError):
            PayPalSandboxConnection('id','secret',MERCHANT,environment='live')
        self.assertNotIn(connection().client_secret,repr(connection()))
        self.assertNotIn(connection().client_id,repr(connection()))

    def test_oauth_capture_and_token_reuse_use_only_fixed_sandbox_paths(self):
        calls=[]
        def handler(req):
            calls.append(req)
            self.assertEqual(str(req.url).split('/v')[0],API_BASE)
            if req.url.path=='/v1/oauth2/token':
                self.assertEqual(req.method,'POST')
                self.assertTrue(req.headers['Authorization'].startswith('Basic '))
                self.assertEqual(req.content,b'grant_type=client_credentials')
                return httpx.Response(200,json=self.token())
            self.assertEqual(req.method,'GET')
            self.assertEqual(req.url.path,f'/v2/payments/captures/{CAPTURE}')
            self.assertEqual(req.headers['Authorization'],'Bearer fixture-bearer-token')
            return httpx.Response(200,json=capture())
        reader=self.client(handler)
        reader.capture(CAPTURE,ORDER); reader.capture(CAPTURE,ORDER)
        self.assertEqual(len(calls),3,'One OAuth exchange, two reads; no HATEOAS link followed')

    def test_token_expiry_fetches_a_new_token(self):
        now=[100]; exchanges=[]
        def handler(req):
            if req.url.path=='/v1/oauth2/token':
                exchanges.append(1); return httpx.Response(200,json=self.token())
            return httpx.Response(200,json=capture())
        reader=self.client(handler,clock=lambda:now[0])
        reader.capture(CAPTURE,ORDER); now[0]=4000; reader.capture(CAPTURE,ORDER)
        self.assertEqual(len(exchanges),2)

    def test_unauthorized_capture_has_only_one_bounded_token_refresh(self):
        calls=[]
        def handler(req):
            calls.append(req.url.path)
            return httpx.Response(200,json=self.token()) if req.url.path=='/v1/oauth2/token' else httpx.Response(401,json={'debug':'fixture-client-secret'})
        with self.assertRaises(ReadFailure) as caught: self.client(handler).capture(CAPTURE,ORDER)
        self.assertEqual(calls.count('/v1/oauth2/token'),2)
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn('fixture-client-secret',str(caught.exception))

    def test_http_errors_are_sanitized_and_rate_limits_retain_delay(self):
        for status in (403,404,429,500):
            def handler(req):
                if req.url.path=='/v1/oauth2/token': return httpx.Response(200,json=self.token())
                return httpx.Response(status,json={'message':'fixture-client-secret'},headers={'Retry-After':'47'})
            with self.subTest(status=status),self.assertRaises(ReadFailure) as caught:
                self.client(handler).capture(CAPTURE,ORDER)
            self.assertNotIn('fixture-client-secret',str(caught.exception))
            self.assertEqual(caught.exception.retryable,status in (429,500))
            if status==429: self.assertEqual(caught.exception.delay,47)

    def test_redirects_are_not_followed_even_if_client_enables_them(self):
        calls=[]
        def handler(req):
            calls.append(req.url.host)
            return httpx.Response(302,headers={'Location':'https://untrusted.example/steal'})
        http=httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=True)
        self.addCleanup(http.close)
        with self.assertRaises(ReadFailure): PayPalSandboxClient(connection(),http).capture(CAPTURE,ORDER)
        self.assertEqual(calls,['api-m.sandbox.paypal.com'])

    def test_bad_oauth_responses_do_not_become_bearer_credentials(self):
        for changed in ({'expires_in':True},{'expires_in':0},{'access_token':'bad\r\ntoken'},
                        {'token_type':'Basic'},{'token_type':None},{'token_type':123},{'access_token':''}):
            body={**self.token(),**changed}
            with self.subTest(changed=list(changed)),self.assertRaises(ReadFailure):
                self.client(lambda req:httpx.Response(200,json=body)).capture(CAPTURE,ORDER)

    def test_invalid_resource_ids_do_not_make_network_requests(self):
        calls=[]
        reader=self.client(lambda req:calls.append(req))
        for identifier in ('../secret','https://untrusted.example/','capture?next=live','lowercase',''):
            with self.assertRaises(ValueError): reader.capture(identifier,ORDER)
        self.assertEqual(calls,[])

    def test_bad_or_oversized_json_is_rejected(self):
        for raw in (b'{"access_token":"one","access_token":"two"}',b'[]',b'{bad',b'x'*(1024*1024+1)):
            with self.subTest(size=len(raw)),self.assertRaises(ReadFailure):
                self.client(lambda req:httpx.Response(200,content=raw)).capture(CAPTURE,ORDER)

    def test_network_timeout_is_sanitized(self):
        def handler(req):
            raise httpx.ReadTimeout('fixture-client-secret',request=req)
        with self.assertRaises(ReadFailure) as caught: self.client(handler).capture(CAPTURE,ORDER)
        self.assertEqual(str(caught.exception),'paypal_network_error')
        self.assertTrue(caught.exception.retryable)


if __name__=='__main__': unittest.main()
