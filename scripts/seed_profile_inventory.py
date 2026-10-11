"""Seed declared synthetic background inventory over HTTP for matched runs.

Run on an empty isolated project with console-worker stopped. Other business
workers fulfill normally. On the new schema, classify only these synthetic jobs
as background via the runtime role, to model a sweep backlog. No admin mutations,
provider faults, money/access changes, or clock edits.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import subprocess
import time

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.demo import seed


def flush_registrations():
    # Fixture preparation: execute the real leased relay/ack path without its
    # one-second production loop pacing. Run only in a fresh isolated project.
    code='''import httpx
from types import SimpleNamespace
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.reference_worker import relay_once
settings=Settings.from_env('reference')
database=Database(settings.database_url)
total=0
try:
    with httpx.Client(timeout=5,trust_env=False) as client:
        app=SimpleNamespace(state=SimpleNamespace(settings=settings,database=database,http=client))
        while True:
            progressed=False
            for workspace in settings.keys:
                if relay_once(app,workspace):
                    total+=1
                    progressed=True
            if not progressed:
                break
finally:
    database.close()
print('Fixture registration messages acknowledged:',total)
'''
    subprocess.run(['docker','compose','exec','-T','reference-worker','python','-c',code],
                   cwd=ROOT,check=True,timeout=180)


def run(a, b):
    env = local_environment()
    url='postgresql://console_runtime:' + env['CONSOLE_DB_PASSWORD'] + '@127.0.0.1:' + env.get('POSTGRES_PORT','15432') + '/console'
    with psycopg2.connect(url) as connection:
        with connection.cursor() as cursor:
            for letter in ('A','B'):
                cursor.execute("SELECT set_config('app.workspace',%s,true)",('ws_' + letter.lower(),))
                cursor.execute('SELECT count(*) FROM purchases')
                if cursor.fetchone()[0]:
                    raise ValueError('Use a fresh isolated project, not an existing inventory')
    def purchase(letter):
        with httpx.Client(timeout=15, trust_env=False) as client:
            fixture=seed(client, env, letter, 'normal')
        return letter, fixture['payment_intent_id']
    fixtures=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for count, fixture in enumerate(pool.map(purchase, ['A'] * a + ['B'] * b), 1):
            fixtures.append(fixture)
            if count % 40 == 0 or count == a + b:
                print(f'Background purchases seeded: {count}/{a+b}', flush=True)
    flush_registrations()
    # Checkout creation is asynchronous: reference-worker registers the purchase
    # and simulator-worker delivers its native hint. Wait before measuring.
    deadline=time.monotonic()+300
    with psycopg2.connect(url) as connection:
        last=None
        while True:
            counts={}
            with connection.cursor() as cursor:
                for letter in ('A','B'):
                    intents=[intent for own,intent in fixtures if own==letter]
                    cursor.execute("SELECT set_config('app.workspace',%s,true)",('ws_' + letter.lower(),))
                    cursor.execute('SELECT count(*) FROM payment_attempts WHERE payment_intent_id=ANY(%s)',(intents,))
                    registered=cursor.fetchone()[0]
                    cursor.execute('SELECT count(DISTINCT payment_intent_id) FROM inbox WHERE payment_intent_id=ANY(%s)',(intents,))
                    notified=cursor.fetchone()[0]
                    counts[letter]=(registered,notified,len(intents))
            connection.commit()
            if counts!=last:
                print('Background readiness (registered, notified, requested): ' + str(counts),flush=True)
                last=counts
            if all(registered==notified==wanted for registered,notified,wanted in counts.values()):
                break
            if time.monotonic()>=deadline:
                raise TimeoutError('Declared background inventory did not become ready')
            time.sleep(2)
    with psycopg2.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM information_schema.columns WHERE table_name='jobs' AND column_name='foreground'")
            if cursor.fetchone():
                for letter in ('A','B'):
                    cursor.execute("SELECT set_config('app.workspace',%s,true)",('ws_' + letter.lower(),))
                    cursor.execute("UPDATE jobs SET foreground=false WHERE payment_intent_id=ANY(%s) AND state='queued'",
                                   ([intent for own,intent in fixtures if own==letter],))
                    print(f'Fixture scheduling labels: {cursor.rowcount} queued {letter} jobs marked background',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--a', type=int, default=320)
    parser.add_argument('--b', type=int, default=32)
    args = parser.parse_args()
    if not 0 <= args.a <= 1000 or not 0 <= args.b <= 1000:
        parser.error('Use 0..1000 purchases per workspace')
    run(args.a, args.b)
