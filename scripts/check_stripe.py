"""Small account-managed Stripe acceptance suite. Never uses anonymous CLI profiles.

Creates synthetic fixtures only with --create-fixtures and a separate test writer.
Requires genuine forwarded webhook receipt plus the runtime's current evidence.
"""

import argparse
from datetime import UTC,datetime
import json
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import STRIPE_API_VERSION,StripeConnection
from backend.app.database import Database
from backend.app.jobs import ReadFailure
from backend.app.stripe_provider import API_BASE,StripeReader
from scripts.check_phase1 import local_environment


def read_env(path):
    if not path.exists():
        raise ValueError('Account-managed Stripe credentials are not configured')
    return dict(line.split('=',1) for line in path.read_text().splitlines() if line and not line.startswith('#'))


class Probe:
    def __init__(self,client,key):
        self.client,self.key=client,key
        self.count=0

    def request(self,method,path,data=None,params=None):
        if self.count>=80 or method not in {'GET','POST'} or not path.startswith('/v1/'):
            raise ReadFailure('acceptance_budget',False)
        self.count+=1
        time.sleep(.25)
        headers={'Authorization':'Bearer '+self.key,'Stripe-Version':STRIPE_API_VERSION}
        if method=='POST':
            headers['Idempotency-Key']='payment-console-check-'+uuid.uuid4().hex
        response=self.client.request(method,API_BASE+path,data=data,params=params,headers=headers)
        if response.status_code>=400:
            code='stripe_acceptance_http_'+str(response.status_code)
            try:
                error=response.json().get('error',{})
                for field in ('code','param'):
                    value=error.get(field)
                    if isinstance(value,str) and re.fullmatch(r'[a-z_]{1,64}',value):
                        code+='_'+field+'_'+value
            except (ValueError,AttributeError):
                pass
            raise ReadFailure(code,False)
        if len(response.content)>1024*1024:
            raise ReadFailure('acceptance_response_budget',False)
        return response.json()

    def get(self,base,path,purpose,params=None):
        if base!=API_BASE or purpose!='stripe':
            raise ReadFailure('acceptance_origin',False)
        return self.request('GET',path,params=params)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create-fixtures',action='store_true')
    args=parser.parse_args()
    report={'checked_at':datetime.now(UTC).isoformat(),'api_version':STRIPE_API_VERSION,
            'source':'genuine_stripe_test_api','complete':False,'checks':[]}
    try:
        env=read_env(ROOT/'.env.stripe')
        if env.get('STRIPE_ENABLED')!='1':
            raise ValueError('Enable the account-managed sandbox after configuring credentials')
        connection=StripeConnection(env.get('STRIPE_WORKSPACE_A_ACCOUNT_ID',''),
                                    env.get('STRIPE_WORKSPACE_A_READ_KEY',''),
                                    env.get('STRIPE_WORKSPACE_A_WEBHOOK_SECRET',''),
                                    env.get('STRIPE_API_VERSION',''))
        if not args.create_fixtures:
            raise ValueError('Run with --create-fixtures after configuring the separate test fixture key and CLI forwarding')
        fixture=read_env(ROOT/'.env.stripe-fixtures')
        writer_key=fixture.get('STRIPE_TEST_FIXTURE_KEY','')
        if not re.fullmatch(r'sk_test_[A-Za-z0-9]{20,256}',writer_key):
            raise ValueError('A separate account-managed test-only fixture key is required')
        local=local_environment()
        suffix=uuid.uuid4().hex
        with httpx.Client(timeout=10,trust_env=False) as client:
            reader_probe=Probe(client,connection.read_key)
            reader=StripeReader(reader_probe,connection)
            reader.verify_account()
            writer=Probe(client,writer_key)
            account=writer.request('GET','/v1/account')
            if account.get('id')!=connection.account_id:
                raise ValueError('Fixture and reader keys must belong to the configured sandbox account')
            customer=writer.request('POST','/v1/customers',data={'description':'Synthetic payment-console acceptance '+suffix})['id']
            purchase_id='stripe_check_'+suffix
            registration={'workspace_id':'ws_a','purchase_id':purchase_id,'customer_id':'customer_'+suffix,
                          'product_id':'digital_pass','expected_amount_minor':2500,'currency':'usd',
                          'connection_id':'stripe_ws_a','provider_customer_id':customer}
            registration_headers={'Authorization':'Bearer '+local['WORKSPACE_A_REGISTRATION_KEY']}
            client.post('http://127.0.0.1:8000/api/purchases',json=registration,headers=registration_headers).raise_for_status()
            data={'amount':'2500','currency':'usd','customer':customer,'payment_method':'pm_card_visa',
                  'automatic_payment_methods[enabled]':'true','automatic_payment_methods[allow_redirects]':'never',
                  'confirm':'true','metadata[purchase_id]':purchase_id}
            intent=writer.request('POST','/v1/payment_intents',data=data)
            if intent.get('livemode') is not False or intent.get('status')!='succeeded':
                raise ValueError('Synthetic payment did not reach a test-mode success')
            client.post('http://127.0.0.1:8001/demo/stripe-targets',json={'purchase_id':purchase_id,
                         'customer_id':registration['customer_id'],'payment_intent_id':intent['id']},
                         headers={'Authorization':'Bearer '+local['WORKSPACE_A_CHECKOUT_KEY']}).raise_for_status()
            client.post(f'http://127.0.0.1:8000/api/purchases/{purchase_id}/payment-attempts',json={'payment_intent_id':intent['id']},headers=registration_headers).raise_for_status()
            payment=reader.payment(registration,intent['id'])
            refunds,disputes=reader.reversals(payment)
            if refunds or disputes:
                raise ValueError('Fresh fixture unexpectedly has reversal history')
            report['checks'].append('successful_payment_current_charge_refund_dispute_reads')
            writer.request('POST','/v1/refunds',data={'payment_intent':intent['id'],'amount':'100'})
            payment=reader.payment(registration,intent['id'])
            refunds,_=reader.reversals(payment)
            if payment['status']!='succeeded' or sum(row['amount_minor'] for row in refunds if row['status']=='succeeded')!=100:
                raise ValueError('Partial refund acceptance did not match expected current facts')
            report['checks'].append('partial_refund_does_not_change_paymentintent_success')
            writer.request('POST','/v1/refunds',data={'payment_intent':intent['id'],'amount':'2400'})
            payment=reader.payment(registration,intent['id'])
            refunds,_=reader.reversals(payment)
            if payment['status']!='succeeded' or sum(row['amount_minor'] for row in refunds if row['status']=='succeeded')!=2500:
                raise ValueError('Full refund acceptance did not match expected current facts')
            report['checks'].append('full_refund_does_not_change_paymentintent_success')
            manual=writer.request('POST','/v1/payment_intents',data=data|{'capture_method':'manual','metadata[purchase_id]':'manual_'+suffix})
            observed=reader.payment({'purchase_id':'manual_'+suffix,'provider_customer_id':customer},manual['id'])
            if observed['status']!='requires_capture' or observed['amount_received_minor']!=0:
                raise ValueError('Manual capture authorization was mistaken for paid success')
            report['checks'].append('manual_capture_is_not_paid_success')
            disputed=writer.request('POST','/v1/payment_intents',data=data|{'payment_method':'pm_card_createDispute','metadata[purchase_id]':'dispute_'+suffix})
            deadline=time.monotonic()+30
            while True:
                disputed_payment=reader.payment({'purchase_id':'dispute_'+suffix,'provider_customer_id':customer},disputed['id'])
                _,disputes=reader.reversals(disputed_payment)
                if disputes:
                    break
                if time.monotonic()>=deadline:
                    raise ValueError('Test dispute was not observed within the acceptance bound')
                time.sleep(2)
            report['checks'].append('genuine_test_dispute_history')
        port=local.get('POSTGRES_PORT','15432')
        database=Database(f"postgresql://console_runtime:{local['CONSOLE_DB_PASSWORD']}@127.0.0.1:{port}/console")
        try:
            deadline=time.monotonic()+45
            while True:
                with database.transaction('ws_a') as cursor:
                    cursor.execute("""SELECT count(*) AS count FROM inbox WHERE connection_id='stripe_ws_a'
                        AND payment_intent_id=%s AND source='authenticated_webhook' AND state='accepted'""", (intent['id'],))
                    receipts=cursor.fetchone()['count']
                    cursor.execute("""SELECT o.facts FROM evidence_heads h JOIN observations o
                        ON o.workspace_id=h.workspace_id AND o.observation_id=h.observation_id
                        WHERE h.purchase_id=%s AND h.generation=o.generation AND o.source='stripe_api_and_target'""", (purchase_id,))
                    row=cursor.fetchone()
                if receipts and row and all(row['facts'][key] for key in ('payment_complete','reversal_complete','access_complete')) and len(row['facts']['refunds'])>=2:
                    break
                if time.monotonic()>=deadline:
                    raise ValueError('Genuine signed forwarding and complete runtime observations were not verified')
                time.sleep(.5)
            report['checks'].append('genuine_signed_webhook_durable_receipt_and_runtime_observation')
        finally:
            database.close()
        report['complete']=True
        (ROOT/'.local').mkdir(exist_ok=True)
        (ROOT/'.local/stripe-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Genuine Stripe sandbox checks passed; sanitized evidence saved under .local.')
        return 0
    except ValueError as error:
        print('Stripe verification incomplete:',str(error))
        return 2
    except (ReadFailure,httpx.HTTPError) as error:
        print('Stripe verification incomplete:',error.code if isinstance(error,ReadFailure) else 'network_or_service_error')
        return 1


if __name__=='__main__':
    sys.exit(main())
