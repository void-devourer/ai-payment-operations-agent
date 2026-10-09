"""Bounded synthetic signed-ingress benchmark, 90% workspace A / 10% B.

Repeated notifications reference two actual simulator purchases; unique event
IDs exercise durable ingestion and job coalescing. This is not a bulk inventory,
unique purchase, Stripe, financial correctness or Internet latency benchmark.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
import uuid

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.demo import seed
from scripts.restore_drill import admin_url


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2) if values else None


def run(rate, seconds, concurrency):
    env = local_environment()
    run_id = 'bench_' + uuid.uuid4().hex
    started_at = datetime.now(UTC).isoformat()
    with httpx.Client(timeout=10, trust_env=False, limits=httpx.Limits(max_connections=concurrency)) as client:
        fixtures = {letter: seed(client, env, letter) for letter in ('A', 'B')}
        def send(index):
            letter = 'B' if index % 10 == 0 else 'A'
            intent = fixtures[letter]['payment_intent_id']
            event = {'id': run_id + '_' + str(index), 'object': 'event', 'api_version': 'simulator.v1',
                     'type': 'payment_intent.succeeded', 'livemode': False, 'created': int(time.time()),
                     'account': 'sim_acct_ws_' + letter.lower(), 'data': {'object': {'id': intent}}}
            raw = json.dumps(event, sort_keys=True, separators=(',', ':')).encode()
            stamp = str(int(time.time()))
            signature = hmac.new(env[f'WORKSPACE_{letter}_WEBHOOK_KEY'].encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
            start = time.monotonic()
            try:
                response = client.post('http://127.0.0.1:8000/webhooks/simulator/sim_ws_' + letter.lower(),
                    content=raw, headers={'Simulator-Signature': f't={stamp},v1={signature}', 'Content-Type': 'application/json'})
                status = response.status_code
            except httpx.RequestError:
                status = 0
            return {'workspace': letter, 'status': status, 'ms': (time.monotonic() - start) * 1000}
        results, pending, skipped = [], set(), 0
        start = time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for index in range(rate * seconds):
                delay = start + index / rate - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                done = {f for f in pending if f.done()}
                results.extend(f.result() for f in done)
                pending -= done
                if len(pending) >= concurrency:
                    skipped += 1
                    continue
                pending.add(pool.submit(send, index))
            results.extend(f.result() for f in pending)
        elapsed = time.monotonic() - start
    status_counts = {str(code): sum(r['status'] == code for r in results) for code in sorted({r['status'] for r in results})}
    acknowledged = sum(200 <= r['status'] < 300 for r in results)
    with psycopg2.connect(admin_url(env, 'console')) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM inbox WHERE event_id LIKE %s', (run_id + '_%',))
            persisted = cursor.fetchone()[0]
            cursor.execute("SELECT workspace_id,extract(epoch from now()-min(created_at)) FROM jobs WHERE state IN ('queued','retry_wait','leased') GROUP BY workspace_id")
            queue_age = {row[0]: round(float(row[1]), 2) for row in cursor.fetchall()}
    result = {'run_id': run_id, 'started_at': started_at, 'host_os': platform.platform(),
              'host_logical_cpus': os.cpu_count(), 'load_client_python': platform.python_version(),
              'requested_rps': rate, 'duration_seconds': seconds, 'concurrency_limit': concurrency,
              'elapsed_seconds': round(elapsed, 2), 'sent': len(results), 'skipped_slots': skipped,
              'status_counts': status_counts, 'acknowledged': acknowledged, 'durable_receipts': persisted,
              'durability_count_matches': acknowledged == persisted,
              'latency_ms': {'p50': percentile([r['ms'] for r in results], .5),
                             'p95': percentile([r['ms'] for r in results], .95),
                             'p99': percentile([r['ms'] for r in results], .99)},
              'workspace_p95_ms': {letter: percentile([r['ms'] for r in results if r['workspace'] == letter], .95) for letter in ('A', 'B')},
              'oldest_active_job_age_seconds_at_end': queue_age,
              'scope': 'Two purchases; unique signed notifications; 90/10 tenant traffic; localhost; job coalescing'}
    output = ROOT / '.local' / 'benchmarks'
    output.mkdir(parents=True, exist_ok=True)
    (output / (run_id + '.json')).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (output / (run_id + '-requests.json')).write_text(json.dumps(results) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rate', type=int, default=25)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--concurrency', type=int, default=16)
    args = parser.parse_args()
    if not 1 <= args.rate <= 100 or not 1 <= args.seconds <= 600 or not 1 <= args.concurrency <= 32:
        parser.error('Use rate 1..100, seconds 1..600, concurrency 1..32')
    try:
        result = run(args.rate, args.seconds, args.concurrency)
        print(json.dumps(result, indent=2))
        if result['skipped_slots'] or not result['durability_count_matches'] or any(k != '200' for k in result['status_counts']):
            sys.exit(1)
    except Exception as error:
        print('Benchmark failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
