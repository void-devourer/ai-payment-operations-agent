"""PayPal invoice wire contracts; all HTTP responses are offline fixtures."""
import copy
from datetime import UTC, datetime, timedelta
import json
import unittest

import httpx

from backend.app.paypal_provider import PayPalSandboxConnection
from backend.app.scope_invoicing import InvoiceError, activate_invoice, create_draft, invoice_number, read_invoice

IDENTIFIER = 'INV2-Z56S-5LLA-Q52L-CPZ5'


def payload():
    return {'invoice_id':'sci_1234567890abcdef', 'recipient_email':'client@example.invalid',
            'client_name':'Example client', 'project_name':'Landing page', 'title':'Contact form',
            'description':'Add a contact form with validation.', 'amount_minor':12000, 'currency':'usd'}


def invoice(state='DRAFT'):
    value = payload()
    return {'id':IDENTIFIER, 'status':state, 'detail':{'invoice_number':invoice_number(value),
        'reference':'scope:'+value['invoice_id'], 'currency_code':'USD', 'invoice_date':'2024-01-01',
        'metadata':{'recipient_view_url':'https://www.sandbox.paypal.com/invoice/p/#Z56S5LLAQ52LCPZ5'}},
        'primary_recipients':[{'billing_info':{'email_address':value['recipient_email']}}],
        'items':[{'name':value['title'], 'description':value['description'], 'quantity':'1',
                  'unit_amount':{'currency_code':'USD', 'value':'120.00'}}],
        'amount':{'currency_code':'USD','value':'120.00'},
        'due_amount':{'currency_code':'USD','value':'0.00' if state=='PAID' else '120.00'}}


class ScopeInvoiceContractTests(unittest.TestCase):
    connection = PayPalSandboxConnection('fixture-client-id','fixture-client-secret','YXZY75W2GKDQE')

    def client(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=True)
        self.addCleanup(client.close)
        return client

    def handler(self, response):
        def handle(request):
            if request.url.path == '/v1/oauth2/token':
                return httpx.Response(200, json={'access_token':'fixture-token', 'token_type':'Bearer', 'expires_in':3600})
            return response(request)
        return handle

    def read(self, value):
        return read_invoice(self.connection, self.client(self.handler(lambda request: httpx.Response(200,json=value))), IDENTIFIER,payload())

    def test_create_fixed_sandbox_draft_exact_decimal_binding_and_never_send(self):
        seen=[]
        def respond(request):
            seen.append(request)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(str(request.url), 'https://api-m.sandbox.paypal.com/v2/invoicing/invoices')
            body=json.loads(request.content)
            self.assertEqual(body['detail']['invoice_number'],invoice_number(payload()))
            self.assertLessEqual(len(body['detail']['invoice_number']),25)
            self.assertEqual(body['detail']['reference'],'scope:'+payload()['invoice_id'])
            self.assertEqual(body['detail']['invoice_date'],(datetime.now(UTC)-timedelta(hours=12)).date().isoformat())
            self.assertEqual(body['items'][0]['unit_amount']['value'],'120.00')
            self.assertEqual(request.headers['Prefer'],'return=representation')
            self.assertFalse(body['configuration']['allow_tip'])
            return httpx.Response(201,json=invoice())
        result=create_draft(self.connection,self.client(self.handler(respond)),payload(),'scope-invoice:sci_123')
        self.assertEqual(result['status'],'draft')
        self.assertIsNone(result['payment_url'])
        self.assertEqual(len(seen),1)

    def test_one_cent_uses_decimal_not_float(self):
        value=payload();value['amount_minor']=1
        def respond(request):
            body=json.loads(request.content)
            self.assertEqual(body['items'][0]['unit_amount']['value'],'0.01')
            result=invoice()
            for field in ('amount','due_amount'):result[field]['value']='0.01'
            result['items'][0]['unit_amount']['value']='0.01'
            return httpx.Response(201,json=result)
        result=create_draft(self.connection,self.client(self.handler(respond)),value,'scope-invoice:one-cent')
        self.assertEqual(result['amount_minor'],1)

    def test_read_exact_states_and_sandbox_payment_link(self):
        self.assertEqual(self.read(invoice('PAID'))['status'],'paid')
        result=self.read(invoice('SENT'))
        self.assertEqual(result['status'],'unpaid')
        self.assertTrue(result['payment_url'].startswith('https://www.sandbox.paypal.com/'))
        self.assertIsNone(self.read(invoice('DRAFT'))['payment_url'])

    def test_manual_partial_pending_cancelled_and_refunded_states_require_review(self):
        for state in ['MARKED_AS_PAID','PAID_EXTERNAL','PARTIALLY_PAID','PAYMENT_PENDING',
                      'REFUNDED','PARTIALLY_REFUNDED','CANCELLED','UNRECOGNIZED']:
            with self.subTest(state=state), self.assertRaises(InvoiceError) as caught:self.read(invoice(state))
            self.assertEqual(caught.exception.code,'paypal_invoice_state_requires_review')

    def test_binding_mismatches_fail_closed_including_items_reference_amount_and_recipient(self):
        for name in ['id','number','reference','recipient','amount','currency','item','description','quantity','due']:
            body=invoice('PAID')
            if name=='id':body['id']='INV2-1111-2222-3333-4444'
            if name=='number':body['detail']['invoice_number']='some other invoice'
            if name=='reference':body['detail']['reference']='scope:other'
            if name=='recipient':body['primary_recipients'][0]['billing_info']['email_address']='other@example.invalid'
            if name=='amount':body['amount']['value']='120.01'
            if name=='currency':body['amount']['currency_code']='EUR'
            if name=='item':body['items'].append(copy.deepcopy(body['items'][0]))
            if name=='description':body['items'][0]['description']='different work'
            if name=='quantity':body['items'][0]['quantity']='2'
            if name=='due':body['due_amount']['value']='120.00'
            with self.subTest(name=name), self.assertRaises(InvoiceError):self.read(body)

    def test_untrusted_or_live_url_is_not_exposed_and_no_url_is_followed(self):
        for url in ['https://www.paypal.com/invoice/p/live', 'https://evil.invalid/invoice/p/x',
                    'javascript:alert(1)', 'https://www.sandbox.paypal.com@evil.invalid/invoice/p/x',
                    'https://www.sandbox.paypal.com:444/invoice/p/x', 'https://www.sandbox.paypal.com/invoice/p/x?redirect=evil',
                    'https://[invalid', 'https://www.sandbox.paypal.com/invoice/p/\nunsafe']:
            body=invoice('SENT');body['detail']['metadata']['recipient_view_url']=url
            with self.subTest(url=url):self.assertIsNone(self.read(body)['payment_url'])

    def test_input_rejected_before_any_network_and_no_scope_truncation(self):
        client=self.client(lambda request:self.fail('must not call network'))
        for key,value in [('amount_minor',True),('amount_minor',0),('amount_minor',1.1),
                          ('currency','eur'),('description','x'*1001),('recipient_email','bad@\nexample.com')]:
            data=payload();data[key]=value
            with self.subTest(key=key),self.assertRaises(InvoiceError):create_draft(self.connection,client,data,'scope-invoice:123')
        with self.assertRaises(InvoiceError):read_invoice(self.connection,client,'../../elsewhere',payload())

    def test_uncertain_creates_are_not_retried_or_exposed_as_failure_to_create(self):
        for response in [httpx.Response(500,text='private upstream'),httpx.Response(201,json={'id':IDENTIFIER}),
                         httpx.Response(307,headers={'location':'https://evil.invalid'}),httpx.Response(201,text='not json')]:
            seen=[]
            def respond(request):seen.append(request);return response
            with self.subTest(status=response.status_code),self.assertRaises(InvoiceError) as caught:
                create_draft(self.connection,self.client(self.handler(respond)),payload(),'scope-invoice:123')
            self.assertTrue(caught.exception.uncertain)
            self.assertFalse(caught.exception.retryable)
            self.assertNotIn('private',str(caught.exception))
            self.assertEqual(len(seen),1)

    def test_network_create_timeout_unknown_but_read_timeout_retryable(self):
        def timeout(request):raise httpx.ReadTimeout('fixture-client-secret private')
        client=self.client(self.handler(timeout))
        with self.assertRaises(InvoiceError) as caught:create_draft(self.connection,client,payload(),'scope-invoice:123')
        self.assertTrue(caught.exception.uncertain)
        with self.assertRaises(InvoiceError) as caught:read_invoice(self.connection,client,IDENTIFIER,payload())
        self.assertFalse(caught.exception.uncertain)
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn('secret',str(caught.exception))

    def test_explicit_request_rejection_has_no_blind_retry(self):
        for status in (400,401,403,406,422,429):
            seen=[]
            def respond(request):seen.append(request);return httpx.Response(status,text='private')
            with self.subTest(status=status),self.assertRaises(InvoiceError) as caught:
                create_draft(self.connection,self.client(self.handler(respond)),payload(),'scope-invoice:123')
            self.assertFalse(caught.exception.uncertain)
            self.assertEqual(len(seen),1)

    def test_activate_prereads_draft_suppresses_all_recipients_and_confirms_payable(self):
        seen=[]
        def respond(request):
            seen.append(request)
            self.assertEqual(request.url.host,'api-m.sandbox.paypal.com')
            if request.method=='POST':
                self.assertEqual(request.url.path,'/v2/invoicing/invoices/'+IDENTIFIER+'/send')
                self.assertEqual(json.loads(request.content),{'send_to_recipient':False,'send_to_invoicer':False,'additional_recipients':[]})
                return httpx.Response(202)
            return httpx.Response(200,json=invoice('DRAFT' if len(seen)==1 else 'SENT'))
        result=activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
        self.assertEqual(result['status'],'unpaid')
        self.assertIsNotNone(result['payment_url'])
        self.assertEqual([request.method for request in seen],['GET','POST','GET'])

    def test_already_payable_or_paid_activation_reads_without_another_write(self):
        for state in ('SENT','PAID'):
            seen=[]
            def respond(request):seen.append(request);return httpx.Response(200,json=invoice(state))
            result=activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
            self.assertIn(result['status'],('unpaid','paid'))
            self.assertEqual([request.method for request in seen],['GET'])

    def test_activation_rejects_future_missing_or_bad_issue_date_and_any_cc_before_write(self):
        for value in ('2999-01-01','not-a-date',None,'2024-1-1'):
            body=invoice();body['detail']['invoice_date']=value
            seen=[]
            def respond(request):seen.append(request);return httpx.Response(200,json=body)
            with self.subTest(value=value),self.assertRaises(InvoiceError) as caught:
                activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
            self.assertEqual(caught.exception.code,'paypal_invoice_issue_date_requires_review')
            self.assertEqual([request.method for request in seen],['GET'])
        body=invoice();body['additional_recipients']=['cc@example.invalid']
        seen=[]
        def respond(request):seen.append(request);return httpx.Response(200,json=body)
        with self.assertRaises(InvoiceError) as caught:
            activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
        self.assertEqual(caught.exception.code,'paypal_invoice_notification_scope_invalid')
        self.assertEqual([request.method for request in seen],['GET'])

    def test_activation_validates_binding_before_write(self):
        body=invoice();body['detail']['reference']='scope:another'
        seen=[]
        def respond(request):seen.append(request);return httpx.Response(200,json=body)
        with self.assertRaises(InvoiceError):
            activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
        self.assertEqual([request.method for request in seen],['GET'])

    def test_activation_post_timeout_or_server_error_is_unknown_without_retry(self):
        for failure in ('timeout','server'):
            seen=[]
            def respond(request):
                seen.append(request)
                if request.method=='GET':return httpx.Response(200,json=invoice())
                if failure=='timeout':raise httpx.ReadTimeout('secret provider detail')
                return httpx.Response(500,text='secret provider detail')
            with self.subTest(failure=failure),self.assertRaises(InvoiceError) as caught:
                activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
            self.assertTrue(caught.exception.uncertain)
            self.assertFalse(caught.exception.retryable)
            self.assertEqual([request.method for request in seen],['GET','POST'])
            self.assertNotIn('secret',str(caught.exception))

    def test_successful_activation_with_failed_or_unconfirmed_readback_is_unknown(self):
        for failure in ('network','still_draft','bad_reference','missing_url','invalid_url'):
            seen=[]
            def respond(request):
                seen.append(request)
                if request.method=='POST':return httpx.Response(200,json={})
                if len(seen)==1:return httpx.Response(200,json=invoice())
                if failure=='network':raise httpx.ReadTimeout('private')
                result=invoice('DRAFT' if failure=='still_draft' else 'SENT')
                if failure=='bad_reference':result['detail']['reference']='scope:wrong'
                if failure=='missing_url':result['detail'].pop('metadata',None)
                if failure=='invalid_url':result['detail']['metadata']['recipient_view_url']='https://evil.invalid/pay'
                return httpx.Response(200,json=result)
            with self.subTest(failure=failure),self.assertRaises(InvoiceError) as caught:
                activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
            self.assertTrue(caught.exception.uncertain)
            self.assertEqual(caught.exception.code,'paypal_invoice_activation_unconfirmed')
            self.assertEqual([request.method for request in seen],['GET','POST','GET'])

    def test_already_unpaid_without_verified_link_requires_review_without_a_send(self):
        body=invoice('SENT');body['detail'].pop('metadata',None)
        seen=[]
        def respond(request):seen.append(request);return httpx.Response(200,json=body)
        with self.assertRaises(InvoiceError) as caught:
            activate_invoice(self.connection,self.client(self.handler(respond)),IDENTIFIER,payload())
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual([request.method for request in seen],['GET'])
