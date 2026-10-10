"""Recorded local-only crash demonstration using the existing integration fault hook.

Seeds a synthetic purchase, waits the real grace period, approves through the
owner API as a labelled test harness, then kills a child after target commit.
No administrator writes, shortened clocks, provider writes, or new operation IDs.
The console worker is briefly stopped and always restarted in finally.
"""
import argparse
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.demo import seed
from scripts.restore_drill import admin_url


def compose(action):
    subprocess.run(['docker', 'compose', action, 'console-worker'], cwd=ROOT,
                   check=True, capture_output=True, timeout=60)


def read_operation(connection, identifier):
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''SELECT operation_id,state,dispatch_started_at,receipt,
            verification_observation_id,lease_until FROM repair_operations WHERE operation_id=%s''', (identifier,))
        operation = dict(cursor.fetchone())
        cursor.execute('SELECT kind,count(*) AS n FROM repair_attempts WHERE operation_id=%s GROUP BY kind', (identifier,))
        operation['attempt_counts'] = {row['kind']: row['n'] for row in cursor.fetchall()}
    return operation


def run(timeout):
    env = local_environment()
    timeline = []
    output = ROOT / '.local' / 'demonstrations'
    output.mkdir(parents=True, exist_ok=True)
    trace_path = output / ('recovery_' + uuid.uuid4().hex + '.json')
    def record(step, **facts):
        event = {'at': datetime.now(UTC).isoformat(), 'step': step, **facts}
        timeline.append(event)
        trace_path.write_text(json.dumps({'complete': False, 'passed': False, 'timeline': timeline},
                                        indent=2, default=str) + '\n', encoding='utf-8')
        print(json.dumps(event, default=str), flush=True)
    with httpx.Client(timeout=10, trust_env=False) as client, closing(psycopg2.connect(admin_url(env, 'console'))) as connection:
        connection.autocommit = True  # Diagnostics only; no long-lived transaction or mutations.
        fixture = seed(client, env, 'A')
        record('synthetic_payment_confirmed_access_missing', purchase_id=fixture['purchase_id'])
        login = client.post('http://127.0.0.1:8000/dev/sessions/owner_a',
                            headers={'X-Demo-Login-Key': env['DEMO_LOGIN_KEY']})
        login.raise_for_status()
        csrf = {'X-CSRF-Token': login.json()['csrf_token']}
        base = 'http://127.0.0.1:8000/api/workspaces/ws_a'
        deadline = time.monotonic() + timeout
        case = None
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute("SELECT case_id FROM cases WHERE purchase_id=%s AND discrepancy_code='PAID_ACCESS_MISSING'", (fixture['purchase_id'],))
                row = cursor.fetchone()
            if row:
                response = client.get(base + '/cases/' + row[0])
                response.raise_for_status()
                candidate = response.json()
                if candidate['evidence_fresh'] and candidate['current_outcome'] == 'eligible':
                    case = candidate
                    break
            time.sleep(2)
        if case is None:
            record('case_wait_timed_out', timeout_seconds=timeout)
            client.post(base + '/sessions/revoke', headers=csrf)
            raise TimeoutError('No fresh eligible case within the declared deadline')
        record('real_grace_elapsed_case_eligible', case_id=case['case_id'])
        stopped = False
        try:
            compose('stop')
            stopped = True
            # The harness approves only its freshly generated synthetic purchase.
            case = client.get(base + '/cases/' + case['case_id']).json()
            response = client.post(base + '/cases/' + case['case_id'] + '/proposals', headers=csrf,
                json={'reason': 'Synthetic crash demonstration: inspect exact evidence',
                      'observation_id': case['latest_observation_id'], 'fingerprint': case['fingerprint']})
            response.raise_for_status()
            proposal = response.json()
            response = client.post(base + '/proposals/' + proposal['proposal_id'] + '/decisions', headers=csrf,
                json={'decision': 'approve', 'payload_digest': proposal['payload_digest'],
                      'reason': 'Local test harness approves its synthetic crash fixture'})
            response.raise_for_status()
            identifier = response.json()['operation_id']
            record('synthetic_owner_approval_committed', operation_id=identifier)
            # Existing hook leases only this operation and calls the actual repair
            # implementation; os._exit(73) occurs after the target HTTP transaction.
            child = subprocess.run([sys.executable, str(ROOT / 'scripts/check_phase4.py'), '--crash-once', identifier],
                                   cwd=ROOT, capture_output=True, timeout=60)
            if child.returncode != 73:
                raise RuntimeError('Child did not reach the declared post-commit crash point')
            access_headers = {'Authorization': 'Bearer ' + env['WORKSPACE_A_ADAPTER_KEY']}
            access = client.get('http://127.0.0.1:8001/internal/access/' + fixture['purchase_id'], headers=access_headers)
            access.raise_for_status()
            before = read_operation(connection, identifier)
            if not (access.json()['revision'] == 1 and access.json()['status'] == 'active'
                    and before['dispatch_started_at'] and before['receipt'] is None and before['state'] == 'executing'):
                raise AssertionError('Post-crash target/console evidence disagrees with the scenario')
            record('child_died_after_target_commit', exit_code=73, target_revision=1,
                   console_state=before['state'], console_receipt_recorded=False)
            crash_at = time.monotonic()
            compose('start')
            stopped = False
            record('normal_worker_restarted_waiting_for_real_lease_expiry')
            recovery_deadline = time.monotonic() + timeout
            after = before
            while time.monotonic() < recovery_deadline:
                after = read_operation(connection, identifier)
                if after['state'] == 'succeeded':
                    break
                if after['state'] in ('blocked', 'conflict', 'applied_not_recovered'):
                    break
                time.sleep(1)
            access = client.get('http://127.0.0.1:8001/internal/access/' + fixture['purchase_id'], headers=access_headers)
            access.raise_for_status()
            case_response = client.get(base + '/cases/' + case['case_id'])
            case_response.raise_for_status()
            passed = (after['state'] == 'succeeded' and after['operation_id'] == identifier
                      and after['receipt'] is not None and after['verification_observation_id'] is not None
                      and after['attempt_counts'].get('dispatch') == 1 and after['attempt_counts'].get('lookup', 0) >= 1
                      and access.json()['revision'] == 1 and access.json()['status'] == 'active'
                      and case_response.json()['state'] == 'resolved')
            record('recovery_verified' if passed else 'recovery_not_verified',
                   seconds_since_crash=round(time.monotonic() - crash_at, 2),
                   operation_state=after['state'], target_revision=access.json()['revision'],
                   attempt_counts=after['attempt_counts'])
            result = {'fixture': fixture, 'operation_id': identifier, 'passed': passed, 'complete': True,
                      'timeline': timeline, 'operation': after,
                      'scope': 'Synthetic owner approval by harness; real grace and lease; actual child death; existing inventory preserved. One observed effect, no universal exactly-once guarantee.'}
            trace_path.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
            return result
        finally:
            if stopped:
                compose('start')
            client.post(base + '/sessions/revoke', headers=csrf)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=int, default=600, help='Separate bounded case and recovery wait, seconds')
    args = parser.parse_args()
    if not 180 <= args.timeout <= 1800:
        parser.error('Use timeout 180..1800 seconds')
    try:
        result = run(args.timeout)
        print(json.dumps({'passed': result['passed'], 'operation_id': result['operation_id']}))
        sys.exit(0 if result['passed'] else 1)
    except Exception as error:
        print('Recovery demonstration failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
