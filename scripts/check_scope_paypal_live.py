"""Explicit sandbox acceptance check through the running application's public API.

--create creates one synthetic project/agreement and queues one $1 sandbox draft.
--activate enables that draft's payment link with the app's notification guards.
--refresh reads its actual provider state. Buyer checkout is a separate human step.
Progress is kept in an ignored local file; never repeat --create after uncertainty.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_scope_setup import read_values

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--create', action='store_true')
    action.add_argument('--activate', action='store_true')
    action.add_argument('--refresh', action='store_true')
    parser.add_argument('--buyer-email')
    parser.add_argument('--workspace', choices=('ws_a', 'ws_b'), default='ws_a')
    args = parser.parse_args()
    state_path = ROOT / '.local' / ('scope-paypal-acceptance.json' if args.workspace == 'ws_a' else 'scope-paypal-acceptance-ws_b.json')
    base = '/api/workspaces/' + args.workspace + '/scope'
    def save(state):
        state_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
    if args.create and (not args.buyer_email or state_path.exists()):
        parser.error('--create requires --buyer-email and no existing acceptance record; inspect existing state before any retry')
    if not args.create and not state_path.exists():
        parser.error('No acceptance record exists')
    state = {} if args.create else json.loads(state_path.read_text(encoding='utf-8'))
    if args.create:
        state_path.parent.mkdir(exist_ok=True)
        with state_path.open('x', encoding='utf-8') as target:
            target.write('{}')
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=25, trust_env=False, follow_redirects=False) as client:
        identity = 'owner_a' if args.workspace == 'ws_a' else 'owner_b'
        login = client.post('/dev/sessions/' + identity, headers={'X-Demo-Login-Key': read_values(ROOT / '.env')['DEMO_LOGIN_KEY']})
        if login.status_code != 200:
            raise RuntimeError('Local operator login failed')
        headers = {'X-CSRF-Token': login.json()['csrf_token']}

        def post(path, body):
            response = client.post(path, json=body, headers=headers)
            if response.status_code != 200:
                raise RuntimeError('Application request rejected: HTTP ' + str(response.status_code))
            return response.json()

        if args.create:
            config = client.get(base + '/config')
            if config.status_code != 200 or config.json()['invoice']['mode'] != 'paypal_sandbox':
                raise RuntimeError('Sandbox invoicing is not configured')
            state['stage'] = 'creating_synthetic_project'
            save(state)
            project = post(base + '/projects', {'name': 'PayPal sandbox acceptance · $1 test',
                'client_name': 'Synthetic sandbox buyer', 'client_email': args.buyer_email,
                'brief': 'One static landing page for $500. Contact forms are excluded. Synthetic integration test only.',
                'base_amount_minor': 50000})
            state['project_id'] = project['project_id']
            path = base + '/projects/' + project['project_id']
            save(state)
            quote = 'Please quote adding one contact form. This is synthetic sandbox test data.'
            project = post(path + '/messages', {'text': quote})
            project = post(path + '/proposals', {'title': 'Contact form · sandbox test',
                'description': 'Add one contact form. $1 synthetic acceptance test; no real client work.',
                'amount_minor': 100, 'expected_brief_revision': project['brief_revision'],
                'evidence': [{'message_id': project['messages'][0]['message_id'], 'quote': quote}]})
            proposal = project['proposals'][0]
            shared = post(path + '/proposals/' + proposal['proposal_id'] + '/share', {'expected_version': proposal['version']})
            token = shared['share_url'].rsplit('/', 1)[-1]
            decision = client.post('/api/scope/review/decision', headers={'Authorization': 'Bearer ' + token},
                json={'decision': 'accepted', 'name': 'Synthetic acceptance test',
                      'proposal_version': proposal['version'], 'proposal_digest': proposal['proposal_digest']})
            if decision.status_code != 200:
                raise RuntimeError('Synthetic client acceptance failed')
            state['stage'] = 'queuing_draft_do_not_repeat_create'
            save(state)
            project = post(path + '/invoices', {'proposal_id': proposal['proposal_id'], 'mode': 'paypal_sandbox'})
            state['invoice_id'] = project['invoices'][0]['invoice_id']
            save(state)
        path = base + '/projects/' + state['project_id']
        invoice_path = path + '/invoices/' + state['invoice_id']
        if args.activate:
            state['stage'] = 'activating_existing_invoice'
            save(state)
            post(invoice_path + '/activate', {})
        if args.refresh:
            post(invoice_path + '/refresh', {})
        for _ in range(25):
            response = client.get(path)
            if response.status_code != 200:
                raise RuntimeError('Could not read project')
            project = response.json()
            invoice = next(row for row in project['invoices'] if row['invoice_id'] == state['invoice_id'])
            if invoice['status'] != 'creating' and (invoice['status'] != 'draft' or invoice['provider_invoice_id']):
                break
            time.sleep(2)
        state.update(stage=invoice['status'], provider_invoice_id=invoice['provider_invoice_id'],
                     last_error=invoice['last_error'], payment_url=invoice['payment_url'])
        save(state)
        print(json.dumps({key: value for key, value in state.items() if key != 'payment_url'}, indent=2))
        return 0 if invoice['status'] in ('draft', 'unpaid', 'paid') and invoice['provider_invoice_id'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (httpx.RequestError, RuntimeError, KeyError, ValueError, OSError) as error:
        print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                          'action': 'Inspect the local acceptance record and existing invoice before retrying.'}))
        sys.exit(1)
