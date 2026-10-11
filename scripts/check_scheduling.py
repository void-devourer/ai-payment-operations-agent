"""Real PostgreSQL scheduling checks in isolated test-only workspace scopes."""
from pathlib import Path
import sys
import unittest
import uuid

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.restore_drill import admin_url
from backend.app.database import Database
from backend.app.jobs import claim, enqueue, finish
from backend.app.reconciliation import schedule_page


class SchedulingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = local_environment()
        cls.database = Database('postgresql://console_runtime:' + cls.env['CONSOLE_DB_PASSWORD']
            + '@127.0.0.1:' + cls.env.get('POSTGRES_PORT', '15432') + '/console')

    @classmethod
    def tearDownClass(cls):
        cls.database.close()

    def setUp(self):
        suffix = uuid.uuid4().hex
        self.workspace, self.connection = 'sched_' + suffix, 'sim_sched_' + suffix
        self.old, self.new = 'old_' + suffix, 'new_' + suffix
        with psycopg2.connect(admin_url(self.env, 'console')) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO connections(workspace_id,connection_id,account_id,environment,api_version) VALUES (%s,%s,%s,'simulated','simulator.v1')",
                               (self.workspace,self.connection,'acct_' + suffix))
                cursor.execute("INSERT INTO purchases VALUES (%s,%s,'customer','digital_pass',2500,'usd',%s,'customer','{}',now())",
                               (self.workspace,'purchase_' + suffix,self.connection))
                cursor.execute('INSERT INTO payment_attempts VALUES (%s,%s,%s,%s)',
                               (self.workspace,'purchase_' + suffix,self.connection,self.old))

    def test_fresh_request_precedes_sweep_and_background_turn_services_sweep(self):
        schedule_page(self.database,self.workspace,self.connection,force=True)
        with self.database.transaction(self.workspace) as cursor:
            enqueue(cursor,self.workspace,self.connection,self.new)
        self.assertEqual(claim(self.database,self.workspace)['payment_intent_id'],self.new)
        self.assertEqual(claim(self.database,self.workspace,foreground_first=False)['payment_intent_id'],self.old)

    def test_sweep_does_not_dirty_a_leased_read(self):
        with self.database.transaction(self.workspace) as cursor:
            enqueue(cursor,self.workspace,self.connection,self.old)
        job=claim(self.database,self.workspace)
        schedule_page(self.database,self.workspace,self.connection,force=True)
        with self.database.transaction(self.workspace) as cursor:
            cursor.execute('SELECT request_seq FROM jobs WHERE job_id=%s',(job['job_id'],))
            self.assertEqual(cursor.fetchone()['request_seq'],job['claimed_seq'])
            finish(cursor,job)
            cursor.execute('SELECT state FROM jobs WHERE job_id=%s',(job['job_id'],))
            self.assertEqual(cursor.fetchone()['state'],'completed')

    def test_sweep_preserves_timer_and_hint_expedites_it(self):
        with self.database.transaction(self.workspace) as cursor:
            identifier=enqueue(cursor,self.workspace,self.connection,self.old)
            cursor.execute("UPDATE jobs SET due_at=now()+interval '120 seconds' WHERE job_id=%s RETURNING due_at,request_seq",(identifier,))
            before=cursor.fetchone()
        schedule_page(self.database,self.workspace,self.connection,force=True)
        with self.database.transaction(self.workspace) as cursor:
            cursor.execute('SELECT due_at,request_seq FROM jobs WHERE job_id=%s',(identifier,))
            self.assertEqual(cursor.fetchone(),before)
            self.assertEqual(enqueue(cursor,self.workspace,self.connection,self.old),identifier)
        self.assertIsNotNone(claim(self.database,self.workspace))


if __name__=='__main__':
    unittest.main(verbosity=2)
