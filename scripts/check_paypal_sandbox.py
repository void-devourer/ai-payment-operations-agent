"""Explicit, capture-only PayPal sandbox smoke check. No payment mutations."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app.jobs import ReadFailure
from backend.app.paypal_provider import PayPalSandboxClient,PayPalSandboxConnection,resource_id


def load_profile(path):
    values={}
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        key,separator,value=line.partition('=')
        key,value=key.strip(),value.strip()
        if not separator or key in values:
            raise ValueError('Invalid PayPal profile')
        values[key]=value
    prefix='PAYPAL_WORKSPACE_A_' if 'PAYPAL_WORKSPACE_A_CLIENT_ID' in values else 'PAYPAL_'
    return PayPalSandboxConnection(values.get(prefix+'CLIENT_ID',''),
        values.get(prefix+'CLIENT_SECRET',''),values.get(prefix+'MERCHANT_ID',''),
        environment=values.get('PAYPAL_ENVIRONMENT','sandbox'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-id',required=True,type=resource_id)
    parser.add_argument('--order-id',required=True,type=resource_id)
    parser.add_argument('--profile',type=Path,default=ROOT/'.env.paypal')
    args=parser.parse_args()
    try:
        connection=load_profile(args.profile)
    except (OSError,ValueError):
        print('PayPal sandbox is not configured. Copy .env.paypal.example to .env.paypal and fill in sandbox seller credentials.',file=sys.stderr)
        return 2
    try:
        with httpx.Client(timeout=5,trust_env=False,follow_redirects=False) as http:
            fact=PayPalSandboxClient(connection,http).capture(args.capture_id,args.order_id)
    except ReadFailure as error:
        print(json.dumps({'ok':False,'code':error.code,'retryable':error.retryable}),file=sys.stderr)
        return 1
    print(json.dumps({'ok':True,'scope':'capture_read_only','capture':asdict(fact),
        'full_provider_acceptance':False,'repair_eligibility':'not_established'},default=str,indent=2))
    return 0


if __name__=='__main__': sys.exit(main())
