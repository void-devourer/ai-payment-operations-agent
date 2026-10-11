"""Bounded diagnostic run of the actual worker; use instead of its normal process.

Runs ordinary leased jobs and reconciliation, with no admin mutations or policy
changes. Output excludes request headers, URLs, payloads, and credentials.
"""
import argparse
from collections import defaultdict
from contextlib import contextmanager, ExitStack
import cProfile
from datetime import UTC, datetime
import json
from pathlib import Path
import pstats
import sys
from threading import Lock
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app import console_worker, evidence, jobs
from backend.app.database import Database


class Finished(Exception):
    pass


def run(seconds, output):
    metrics = defaultdict(lambda: {'calls': 0, 'seconds': 0.0})
    reads = []
    queues = {}
    metric_lock=Lock()
    deadline = time.monotonic() + seconds
    started = datetime.now(UTC).isoformat()

    def timed(name, original):
        def measured(*args, **kwargs):
            start = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                with metric_lock:
                    metrics[name]['calls'] += 1
                    metrics[name]['seconds'] += time.monotonic() - start
        return measured

    original_transaction = Database.transaction
    @contextmanager
    def transaction(database, *args, **kwargs):
        start = time.monotonic()
        try:
            with original_transaction(database, *args, **kwargs) as cursor:
                yield cursor
        finally:
            with metric_lock:
                metrics['database_transactions']['calls'] += 1
                metrics['database_transactions']['seconds'] += time.monotonic() - start

    original_claim = console_worker.claim
    def claim(database, workspace, *args, **kwargs):
        if workspace not in queues:
            with database.transaction(workspace) as cursor:
                cursor.execute("SELECT state,count(*) AS n FROM jobs GROUP BY state")
                queues[workspace] = {row['state']: row['n'] for row in cursor.fetchall()}
        job = original_claim(database, workspace, *args, **kwargs)
        if job:
            reads.append({'workspace': workspace,
                'due_wait_seconds': max(0, (datetime.now(UTC) - job['due_at']).total_seconds()),
                'attempt': job['attempts']})
        return job

    original_round = console_worker.run_one
    def one(app, workspace, *args, **kwargs):
        if time.monotonic() >= deadline:
            raise Finished()
        return timed('job_round_' + workspace, original_round)(app, workspace, *args, **kwargs)

    original_stream = __import__('httpx').Client.stream
    @contextmanager
    def stream(client, *args, **kwargs):
        start = time.monotonic()
        try:
            with original_stream(client, *args, **kwargs) as response:
                yield response
        finally:
            with metric_lock:
                metrics['source_http']['calls'] += 1
                metrics['source_http']['seconds'] += time.monotonic() - start

    profiler = cProfile.Profile()
    profiles = [profiler]
    with ExitStack() as stack, patch.object(Database, 'transaction', transaction), \
         patch.object(console_worker, 'claim', claim), \
         patch.object(console_worker, 'run_one', one), \
         patch.object(console_worker, 'schedule_page', timed('sweep', console_worker.schedule_page)), \
         patch.object(console_worker, 'run_repair', timed('repair_round', console_worker.run_repair)), \
         patch.object(evidence.Reader, 'get', timed('bounded_source_read', evidence.Reader.get)), \
         patch.object(evidence, 'reserve_request', timed('reserve_request', jobs.reserve_request)), \
         patch.object(__import__('httpx').Client, 'stream', stream):
        if hasattr(console_worker, 'run_workspace'):
            original_workspace = console_worker.run_workspace
            def workspace(*args, **kwargs):
                thread_profile = cProfile.Profile()
                profiles.append(thread_profile)
                return thread_profile.runcall(original_workspace, *args, **kwargs)
            stack.enter_context(patch.object(console_worker, 'run_workspace', workspace))
        try:
            profiler.runcall(console_worker.main)
        except Finished:
            pass
    stats = pstats.Stats(profiler)
    for profile in profiles[1:]:
        stats.add(profile)
    top = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:20]
    result = {'started_at': started, 'finished_at': datetime.now(UTC).isoformat(),
              'declared_seconds': seconds, 'initial_job_counts': queues,
              'timings': dict(metrics), 'claimed_reads': reads,
              'profile': [{'function': Path(key[0]).name + ':' + str(key[1]) + ':' + key[2],
                           'calls': value[1], 'self_seconds': value[2], 'cumulative_seconds': value[3]}
                          for key, value in top],
              'scope': 'Actual worker process with diagnostic wrappers. Timings overlap (including concurrent loops); do not sum them. No admin writes or changed request budgets.'}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'claimed_reads'}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 900:
        parser.error('Use 10..900 seconds')
    run(args.seconds, args.output)
