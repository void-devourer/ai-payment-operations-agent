"""End-to-end synthetic investigation benchmark; real grace, no database writes.

Distinct purchases across the two supported workspaces, mixed final states,
extra workspace-A notifications, and an optional real console-worker restart.
Run separately from integration suites. Existing inventory is preserved/reported.
"""
import argparse
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import hmac
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_release import percentile
from scripts.check_phase1 import local_environment
from scripts.demo import seed
from scripts.restore_drill import admin_url


def notify(client, env, fixture, event_id):
    letter = fixture['letter']
    event = {'id': event_id, 'object': 'event', 'api_version': 'simulator.v1',
             'type': 'payment_intent.succeeded', 'livemode': False, 'created': int(time.time()),
             'account': 'sim_acct_ws_' + letter.lower(),
             'data': {'object': {'id': fixture['payment_intent_id']}}}
    raw = json.dumps(event, sort_keys=True, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(env[f'WORKSPACE_{letter}_WEBHOOK_KEY'].encode(),
                         stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    started = time.monotonic()
    response = client.post('http://127.0.0.1:8000/webhooks/simulator/sim_ws_' + letter.lower(),
        content=raw, headers={'Simulator-Signature': f't={stamp},v1={signature}',
                             'Content-Type': 'application/json'})
    response.raise_for_status()
    return {'event_id': event_id, 'status': response.status_code,
            'ack_ms': round((time.monotonic() - started) * 1000, 2)}


def matches(facts, scenario):
    if not all(facts.get(key) is True for key in ('payment_complete', 'reversal_complete', 'access_complete')):
        return False
    payments, access = facts.get('payments', []), facts.get('access') or {}
    if len(payments) != 1 or facts.get('disputes'):
        return False
    return (payments[0]['status'] == ('failed' if scenario == 'failed' else 'succeeded')
            and payments[0].get('currency') == 'usd'
            and payments[0].get('amount_received_minor') == (0 if scenario == 'failed' else 2500)
            and access.get('status') == ('active' if scenario == 'normal' else 'inactive')
            and access.get('revision') == (1 if scenario == 'normal' else 0)
            and bool(facts.get('refunds')) == (scenario == 'refunded'))


def snapshot(connection, fixtures):
    identifiers = [f['purchase_id'] for f in fixtures]
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('''SELECT o.purchase_id,o.started_at,o.finished_at,o.facts,e.outcome
            FROM observations o JOIN evaluations e USING(workspace_id,observation_id)
            WHERE o.purchase_id=ANY(%s) ORDER BY o.finished_at''', (identifiers,))
        observations = cursor.fetchall()
        cursor.execute('SELECT purchase_id,discrepancy_code,state,opened_at FROM cases WHERE purchase_id=ANY(%s)', (identifiers,))
        cases = cursor.fetchall()
        cursor.execute('SELECT event_id,received_at FROM inbox WHERE event_id=ANY(%s)', ([f['event_id'] for f in fixtures],))
        receipts = {row['event_id']: row['received_at'] for row in cursor.fetchall()}
        cursor.execute('''SELECT a.purchase_id,s.first_confirmed_at FROM success_clocks s
            JOIN payment_attempts a USING(workspace_id,connection_id,payment_intent_id)
            WHERE a.purchase_id=ANY(%s)''', (identifiers,))
        clocks = {row['purchase_id']: row['first_confirmed_at'] for row in cursor.fetchall()}
        cursor.execute('''SELECT count(*) AS unauthorized_repairs FROM repair_operations
            WHERE purchase_id=ANY(%s)''', (identifiers,))
        repairs = cursor.fetchone()['unauthorized_repairs']
    result = []
    for fixture in fixtures:
        receipt = receipts.get(fixture['event_id'])
        rows = [row for row in observations if row['purchase_id'] == fixture['purchase_id']
                and receipt and row['started_at'] >= receipt and matches(row['facts'], fixture['kind'])]
        own_cases = [row for row in cases if row['purchase_id'] == fixture['purchase_id']]
        expected = {'normal': 'healthy', 'failed': 'blocked', 'refunded': 'manual_review', 'missing': 'eligible'}[fixture['kind']]
        evaluated = next((row for row in rows if row['outcome'] == expected), None)
        code = {'missing': 'PAID_ACCESS_MISSING', 'refunded': 'REVERSAL_ACCESS_REVIEW'}.get(fixture['kind'])
        case = next((row for row in own_cases if row['discrepancy_code'] == code), None)
        wrong_cases = [row['discrepancy_code'] for row in own_cases if row['discrepancy_code'] != code]
        evidence_seconds = (rows[0]['finished_at'] - receipt).total_seconds() if rows else None
        decision_seconds = (evaluated['finished_at'] - receipt).total_seconds() if evaluated else None
        grace_lag = ((case['opened_at'] - clocks[fixture['purchase_id']]).total_seconds() - 120
                     if case and fixture['kind'] == 'missing' and fixture['purchase_id'] in clocks else None)
        result.append({**fixture, 'receipt_at': receipt.isoformat() if receipt else None,
                       'complete_evidence_seconds': round(evidence_seconds, 2) if evidence_seconds is not None else None,
                       'expected_decision_seconds': round(decision_seconds, 2) if decision_seconds is not None else None,
                       'case_opened_at': case['opened_at'].isoformat() if case else None,
                       'post_grace_detection_seconds': round(grace_lag, 2) if grace_lag is not None else None,
                       'wrong_cases': wrong_cases,
                       'passed': evaluated is not None and (code is None or case is not None) and not wrong_cases})
    return result, repairs


def run(per_workspace, noisy_seconds, noisy_rate, timeout, restart):
    env = local_environment()
    run_id = 'investigation_' + uuid.uuid4().hex
    started_at = datetime.now(UTC).isoformat()
    fixtures, notifications, restart_record = [], [], None
    with closing(psycopg2.connect(admin_url(env, 'console'))) as connection, httpx.Client(timeout=10, trust_env=False) as client:
        # Read-only diagnostics use one autocommit connection: no long snapshot or DB mutations.
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('SELECT workspace_id,count(*) FROM purchases GROUP BY workspace_id')
            baseline = dict(cursor.fetchall())
        for letter in ('A', 'B'):
            for index in range(per_workspace):
                kind = ('normal', 'missing', 'refunded', 'failed')[index % 4]
                fixture = seed(client, env, letter, 'normal' if kind == 'normal' else 'missing-access')
                headers = {'Authorization': 'Bearer ' + env[f'WORKSPACE_{letter}_PROVIDER_KEY']}
                intent = fixture['payment_intent_id']
                if kind == 'refunded':
                    client.post(f'http://127.0.0.1:8002/internal/payments/{intent}/refunds',
                        headers=headers, json={'resource_id': 'refund_' + uuid.uuid4().hex,
                                             'status': 'succeeded', 'amount_minor': 2500}).raise_for_status()
                elif kind == 'failed':
                    client.post(f'http://127.0.0.1:8002/internal/payments/{intent}/scenario',
                        headers=headers, json={'status': 'failed'}).raise_for_status()
                fixture.update(letter=letter, kind=kind, event_id=run_id + '_' + str(len(fixtures)))
                fixtures.append(fixture)
        # Both tenants have registered inventory before noisy traffic begins.
        for fixture in fixtures:
            notifications.append(notify(client, env, fixture, fixture['event_id']))
        noise_start = time.monotonic()
        skipped = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            pending = set()
            for index in range(noisy_seconds * noisy_rate):
                delay = noise_start + index / noisy_rate - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                done = {future for future in pending if future.done()}
                notifications.extend(future.result() for future in done)
                pending -= done
                if len(pending) >= 8:
                    skipped += 1
                    continue
                fixture = fixtures[index % per_workspace]
                pending.add(pool.submit(notify, client, env, fixture, run_id + '_noise_' + str(index)))
            notifications.extend(future.result() for future in pending)
        if restart:
            restart_started = time.monotonic()
            subprocess.run(['docker', 'compose', 'restart', 'console-worker'], cwd=ROOT,
                           check=True, capture_output=True, timeout=60)
            restart_record = {'at': datetime.now(UTC).isoformat(),
                              'command_seconds': round(time.monotonic() - restart_started, 2),
                              'scope': 'graceful container restart; not a process-kill/abandoned-lease test'}
        deadline = time.monotonic() + timeout
        last_status, last_log = None, 0
        while True:
            records, repairs = snapshot(connection, fixtures)
            passed = sum(row['passed'] for row in records)
            if (passed, repairs) != last_status or time.monotonic() - last_log >= 30:
                print(f'Investigation outcomes: {passed}/{len(fixtures)}; automatic repairs: {repairs}', flush=True)
                last_status, last_log = (passed, repairs), time.monotonic()
            if passed == len(fixtures) or time.monotonic() >= deadline:
                break
            time.sleep(5)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM inbox WHERE event_id=ANY(%s)', ([r['event_id'] for r in notifications],))
            persisted = cursor.fetchone()[0]
            cursor.execute('''SELECT workspace_id,count(*) FROM jobs WHERE state IN ('queued','retry_wait','leased')
                GROUP BY workspace_id''')
            active_jobs = dict(cursor.fetchall())
    metrics = {}
    for letter in ('A', 'B'):
        own = [row for row in records if row['letter'] == letter]
        metrics[letter] = {'purchases': len(own), 'passed': sum(row['passed'] for row in own),
            'measured_counts': {key: sum(row[key] is not None for row in own) for key in
                ('complete_evidence_seconds', 'expected_decision_seconds', 'post_grace_detection_seconds')},
            **{key: {'p50': percentile([row[key] for row in own if row[key] is not None], .5),
                     'p95': percentile([row[key] for row in own if row[key] is not None], .95)} for key in
                ('complete_evidence_seconds', 'expected_decision_seconds', 'post_grace_detection_seconds')}}
    result = {'run_id': run_id, 'started_at': started_at, 'host_os': platform.platform(),
              'python': platform.python_version(), 'baseline_purchase_counts': baseline,
              'per_workspace': per_workspace, 'noisy_workspace': 'A', 'noisy_seconds': noisy_seconds,
              'noisy_requested_rps': noisy_rate, 'noise_skipped_slots': skipped,
              'notifications': len(notifications), 'durable_receipts': persisted,
              'webhook_ack_p95_ms': percentile([row['ack_ms'] for row in notifications], .95),
              'worker_restart': restart_record, 'timeout_after_noise_seconds': timeout,
              'workspace_metrics': metrics, 'automatic_repairs': repairs,
              'active_jobs_at_end_including_background': active_jobs, 'records': records,
              'passed': all(row['passed'] for row in records) and not repairs
                        and persisted == len(notifications) and skipped == 0,
              'scope': 'Two fixed workspaces; real 120s grace; mixed distinct synthetic purchases; no approvals/money movement; existing inventory preserved. No global freshness SLA.'}
    output = ROOT / '.local' / 'benchmarks'
    output.mkdir(parents=True, exist_ok=True)
    (output / (run_id + '.json')).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--per-workspace', type=int, default=12)
    parser.add_argument('--noisy-seconds', type=int, default=30)
    parser.add_argument('--noisy-rate', type=int, default=10)
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--restart-worker', action='store_true')
    args = parser.parse_args()
    if not 4 <= args.per_workspace <= 100 or args.per_workspace % 4 or not 1 <= args.noisy_seconds <= 120 or not 1 <= args.noisy_rate <= 25 or not 120 <= args.timeout <= 1800:
        parser.error('Use a multiple of 4 purchases per workspace (4..100), noise 1..120s at 1..25rps, timeout 120..1800s')
    try:
        result = run(args.per_workspace, args.noisy_seconds, args.noisy_rate, args.timeout, args.restart_worker)
        print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))
        sys.exit(0 if result['passed'] else 1)
    except Exception as error:
        print('Investigation benchmark failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
