"""Opt-in, isolated genuine Stripe smoke test; never enables the console adapter.

Requires a freshly provisioned ignored CLI profile. Temporary credentials have
limited permissions, so passing this test cannot satisfy full Stripe acceptance.
"""

import argparse
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import tomllib
from types import SimpleNamespace
import uuid

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.config import STRIPE_API_VERSION
from backend.app.ingestion import verify_signature
from backend.app.stripe_provider import parse_stripe_event
from scripts.check_stripe import Probe
from backend.app.jobs import ReadFailure


def temporary_profile(path):
    profile=tomllib.loads(path.read_text()).get('default',{})
    expiry=date.fromisoformat(profile.get('sandbox_expires_at',''))
    if datetime.now(UTC).date()>=expiry:
        raise ValueError('Temporary sandbox expired; provision a fresh private profile')
    if not re.fullmatch(r'rkcs_test_[A-Za-z0-9]{20,256}',profile.get('test_mode_api_key','')):
        raise ValueError('Expected an anonymous sandbox key in the isolated CLI profile')
    if not re.fullmatch(r'acct_[A-Za-z0-9]{8,80}',profile.get('account_id','')):
        raise ValueError('Temporary sandbox account ID missing')
    return profile,expiry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--create-fixtures',action='store_true')
    args=parser.parse_args()
    if not args.create_fixtures:
        print('Requires --create-fixtures; creates synthetic test-only Stripe resources.')
        return 2
    server=listener=log=None
    try:
        profile_path=ROOT/'.local/stripe-verification-profile.toml'
        profile,expiry=temporary_profile(profile_path)
        cli=ROOT/'.tools/stripe/node_modules/@stripe/cli-win32-x64/bin/stripe.exe'
        env=os.environ.copy()
        env['STRIPE_API_KEY']=profile['test_mode_api_key']
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        secret_result=subprocess.run([str(cli),'listen','--config',str(profile_path),'--print-secret','--latest'],
            env=env,capture_output=True,timeout=30,creationflags=flags)
        match=re.search(rb'whsec_[A-Za-z0-9]+',secret_result.stdout+secret_result.stderr)
        if secret_result.returncode or not match:
            raise ValueError('Could not obtain the temporary listener signing secret')
        connection=SimpleNamespace(account_id=profile['account_id'],api_version=STRIPE_API_VERSION,
            webhook_secret=match.group().decode())
        receipts=[]
        rejected=[]
        lock=threading.Lock()
        class Receiver(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def do_POST(self):
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if self.path!='/stripe' or not 0<length<=1024*1024:
                        raise ValueError('invalid_request')
                    self.connection.settimeout(5)
                    raw=self.rfile.read(length)
                    verify_signature(raw,self.headers.get('Stripe-Signature',''),connection.webhook_secret)
                    event,state,intent=parse_stripe_event(raw,connection)
                    if state!='accepted':
                        raise ValueError('unsupported_event_or_version')
                    with lock:
                        receipts.append((event['type'],intent))
                    self.send_response(200)
                except (ValueError,TimeoutError):
                    with lock:
                        rejected.append('signature_envelope_or_version')
                    self.send_response(400)
                self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',8010),Receiver)
        server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        log=(ROOT/'.local/stripe-temporary-listener-private.log').open('wb')
        listener=subprocess.Popen([str(cli),'listen','--config',str(profile_path),'--latest',
            '--events-from','@self','--events',
            'payment_intent.succeeded,payment_intent.amount_capturable_updated,charge.refunded,refund.created,refund.updated',
            '--forward-to','http://127.0.0.1:8010/stripe'],env=env,stdout=log,stderr=log,creationflags=flags)
        time.sleep(3)
        if listener.poll() is not None:
            raise ValueError('Temporary listener exited before fixture creation')
        report={'checked_at':datetime.now(UTC).isoformat(),'api_version':STRIPE_API_VERSION,
            'sandbox_expires_at':expiry.isoformat(),'source':'genuine_stripe_temporary_sandbox',
            'full_acceptance_complete':False,'checks':[],
            'limitations':['No console database or runtime adapter integration',
                'Account identity read denied by temporary key',
                'Dispute read denied by temporary key; reversal completeness unverified']}
        with httpx.Client(timeout=10,trust_env=False) as client:
            headers={'Authorization':'Bearer '+profile['test_mode_api_key'],'Stripe-Version':STRIPE_API_VERSION}
            for path in ('/v1/account','/v1/disputes'):
                response=client.get('https://api.stripe.com'+path,headers=headers)
                if response.status_code!=403:
                    raise ValueError('Temporary permissions changed; reassess full acceptance separately')
            writer=Probe(client,profile['test_mode_api_key'])
            customer=writer.request('POST','/v1/customers',data={'description':'Synthetic temporary verification '+uuid.uuid4().hex})
            data={'amount':'2500','currency':'usd','customer':customer['id'],
                'payment_method':'pm_card_visa','automatic_payment_methods[enabled]':'true',
                'automatic_payment_methods[allow_redirects]':'never','confirm':'true'}
            intent=writer.request('POST','/v1/payment_intents',data=data)
            if intent.get('livemode') is not False or intent.get('status')!='succeeded' or intent.get('amount_received')!=2500:
                raise ValueError('Test payment did not succeed')
            report['checks'].append('genuine_test_payment_success')
            for amount,total in ((100,100),(2400,2500)):
                refund=writer.request('POST','/v1/refunds',data={'payment_intent':intent['id'],'amount':str(amount)})
                current=writer.request('GET','/v1/payment_intents/'+intent['id'])
                charges=writer.request('GET','/v1/charges',params={'payment_intent':intent['id'],'limit':20})
                refunds=writer.request('GET','/v1/refunds',params={'payment_intent':intent['id'],'limit':20})
                if (refund.get('status')!='succeeded' or current.get('livemode') is not False or
                    current.get('status')!='succeeded' or current.get('customer')!=customer['id'] or
                    charges.get('has_more') is not False or refunds.get('has_more') is not False or
                    not charges.get('data') or any(c.get('livemode') is not False or c.get('payment_intent')!=intent['id'] for c in charges['data']) or
                    any(r.get('payment_intent')!=intent['id'] for r in refunds['data']) or
                    sum(r['amount'] for r in refunds['data'] if r['status']=='succeeded')!=total or
                    sum(c['amount_refunded'] for c in charges['data'])!=total):
                    raise ValueError('Current charge/refund facts did not match synthetic refund')
                report['checks'].append('partial_refund_current_reads' if total==100 else 'full_refund_current_reads')
            manual=writer.request('POST','/v1/payment_intents',data=data|{'capture_method':'manual'})
            if manual.get('livemode') is not False or manual.get('status')!='requires_capture' or manual.get('amount_received')!=0:
                raise ValueError('Manual authorization was mistaken for payment success')
            report['checks'].append('manual_capture_is_not_paid_success')
        deadline=time.monotonic()+45
        while True:
            with lock:
                matching={kind for kind,binding in receipts if binding==intent['id']}
            if 'payment_intent.succeeded' in matching and matching.intersection({'charge.refunded','refund.created','refund.updated'}):
                break
            if listener.poll() is not None or time.monotonic()>=deadline:
                raise ValueError('Genuine signed payment/refund delivery was not verified')
            time.sleep(.5)
        report['checks'].append('genuine_signed_payment_and_refund_webhooks_at_pinned_version')
        report['smoke_test_complete']=True
        report['authenticated_webhook_count']=len(receipts)
        report['rejected_webhook_count']=len(rejected)
        (ROOT/'.local/stripe-temporary-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Genuine temporary Stripe smoke checks passed. Full acceptance remains incomplete (account/dispute permissions).')
        return 0
    except (ValueError,OSError,subprocess.SubprocessError,ReadFailure,httpx.HTTPError) as error:
        print('Temporary Stripe verification incomplete:',error.code if isinstance(error,ReadFailure) else type(error).__name__)
        return 1
    finally:
        if listener is not None and listener.poll() is None:
            listener.terminate()
            try:
                listener.wait(timeout=5)
            except subprocess.TimeoutExpired:
                listener.kill()
                listener.wait(timeout=5)
        if server is not None:
            server.shutdown()
            server.server_close()
        if log is not None:
            log.close()


if __name__=='__main__':
    sys.exit(main())
