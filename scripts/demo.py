"""Create one synthetic scenario through public/service HTTP contracts only.

No administrator mutations, shortened grace, direct grants or approvals. The
owner still reviews the exact repair payload in the console.
"""
import argparse
import json
import re
from pathlib import Path
import sys
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment


def seed(client, env, letter='A', scenario='missing-access'):
    suffix = uuid.uuid4().hex
    purchase = 'demo_' + suffix
    customer = 'synthetic_' + suffix
    def headers(purpose):
        return {'Authorization': 'Bearer ' + env[f'WORKSPACE_{letter}_{purpose}_KEY']}
    body = {'purchase_id': purchase, 'customer_id': customer,
            'fault_mode': 'none' if scenario == 'normal' else 'pause_fulfillment'}
    response = client.post('http://127.0.0.1:8001/demo/checkouts', json=body, headers=headers('CHECKOUT'))
    response.raise_for_status()
    intent = response.json()['payment_intent_id']
    client.post(f'http://127.0.0.1:8001/demo/checkouts/{purchase}/pay', headers=headers('CHECKOUT')).raise_for_status()
    if scenario == 'provider-outage':
        client.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',
                    json={'read_fault': 503}, headers=headers('PROVIDER')).raise_for_status()
    return {'workspace_id': 'ws_' + letter.lower(), 'purchase_id': purchase,
            'payment_intent_id': intent, 'scenario': scenario, 'simulated': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--scenario', choices=['normal', 'missing-access', 'provider-outage'], default='missing-access')
    action.add_argument('--clear-fault', metavar='SIMULATED_INTENT_ID', help='Clear a simulator read/page fault without changing payment status')
    parser.add_argument('--workspace', choices=['A', 'B'], default='A')
    args = parser.parse_args()
    if args.clear_fault and not re.fullmatch(r'sim_pi_[a-f0-9]{32}', args.clear_fault):
        parser.error('Use the printed simulator payment intent ID')
    with httpx.Client(timeout=10, trust_env=False) as client:
        env = local_environment()
        if args.clear_fault:
            client.post(f'http://127.0.0.1:8002/internal/payments/{args.clear_fault}/scenario',
                        json={'read_fault': 0, 'page_fault': False},
                        headers={'Authorization': 'Bearer ' + env[f'WORKSPACE_{args.workspace}_PROVIDER_KEY']}).raise_for_status()
            print('Simulator fault cleared. Wait for retry, or redrive the job if it is dead.')
            return
        result = seed(client, env, args.workspace, args.scenario)
    directory = ROOT / '.local'
    directory.mkdir(exist_ok=True)
    (directory / 'demo-latest.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    print('Open http://127.0.0.1:8000.')
    if args.scenario == 'missing-access':
        print('Missing access becomes a case after the real 120-second grace and the next evidence read.')
    elif args.scenario == 'normal':
        print('The independent reference worker should activate access without a console repair.')
    else:
        print('Provider reads return 503; incomplete evidence must not authorize a repair.')
    print('Local login key stays in .env; no approval is performed by this script.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Demo failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
