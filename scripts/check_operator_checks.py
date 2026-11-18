"""Scoped, CSRF-protected real-source checks; pauses workers for durable fixtures.

Reuses Phase 3's declared synthetic grace-clock fixture. No live payments.
"""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_phase3 import Phase3IntegrationTests as P3
from scripts.check_phase2 import WORKERS
from backend.app.evidence import collect
from backend.app.jobs import fail,ReadFailure


class OperatorChecks(unittest.TestCase):
    setUpClass=classmethod(P3.setUpClass.__func__)
    tearDownClass=classmethod(P3.tearDownClass.__func__)
    headers=P3.headers
    purchase=P3.purchase
    lease=P3.lease
    admin=P3.admin
    refresh=P3.refresh
    overdue=P3.overdue
    cases=P3.cases
    login=P3.login

    def fixture(self):
        purchase,intent=self.overdue()
        case=self.cases(purchase['purchase_id'])[0]
        return case,intent,'http://127.0.0.1:8000/api/workspaces/ws_a/cases/'+case['case_id']

    def test_01_authorization_scoped_status_and_real_read(self):
        case,intent,url=self.fixture()
        self.http.cookies.clear()
        self.assertEqual(self.http.post(url+'/check').status_code,401)
        viewer=self.login('viewer_a')
        self.assertEqual(self.http.post(url+'/check',headers=viewer).status_code,403)
        owner=self.login()
        self.assertEqual(self.http.post(url+'/check').status_code,403)
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses=list(pool.map(lambda _:self.http.post(url+'/check',headers=owner),range(4)))
        self.assertEqual(sorted(r.status_code for r in responses),[202,429,429,429])
        accepted=next(r for r in responses if r.status_code==202)
        self.assertEqual(accepted.status_code,202)
        check=accepted.json()
        availability=self.http.get(url+'/check-availability')
        self.assertEqual(availability.status_code,200)
        self.assertFalse(availability.json()['allowed'])
        self.assertGreater(availability.json()['retry_after_seconds'],0)
        status_url=url+'/checks/'+check['job_id']
        self.assertEqual(self.http.get(status_url).json()['state'],'queued')
        self.assertEqual(self.http.post(url+'/check',headers=owner).status_code,429)
        collect(self.app,self.lease(intent))
        status=self.http.get(status_url).json()
        self.assertEqual(status['state'],'completed')
        self.assertGreaterEqual(datetime.fromisoformat(status['started_at']),datetime.fromisoformat(check['requested_at']))
        self.assertNotEqual(status['observation_id'],case['latest_observation_id'])
        other,_,other_url=self.fixture()
        self.assertEqual(self.http.get(other_url+'/checks/'+check['job_id']).status_code,404)
        self.login('owner_b')
        self.assertEqual(self.http.get(status_url).status_code,403)
        self.assertEqual(self.http.get(url+'/check-availability').status_code,403)

    def test_02_existing_retry_delay_is_preserved(self):
        _,intent,url=self.fixture()
        with self.database.transaction('ws_a') as cursor:
            from backend.app.jobs import enqueue
            enqueue(cursor,'ws_a','sim_ws_a',intent)
        leased=self.lease(intent)
        fail(self.database,leased,ReadFailure('provider_rate_limit',delay=90))
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT due_at,request_seq FROM jobs WHERE job_id=%s',(leased['job_id'],))
            before=cursor.fetchone()
        accepted=self.http.post(url+'/check',headers=self.login())
        self.assertEqual(accepted.status_code,202)
        status=self.http.get(url+'/checks/'+accepted.json()['job_id']).json()
        self.assertEqual(status['state'],'retry_wait')
        self.assertEqual(datetime.fromisoformat(status['due_at']),before['due_at'])
        with self.database.transaction('ws_a') as cursor:
            cursor.execute('SELECT request_seq FROM jobs WHERE job_id=%s',(leased['job_id'],))
            self.assertEqual(cursor.fetchone()['request_seq'],before['request_seq']+1)

    def test_03_workspace_quota_across_distinct_cases(self):
        owner=self.login()
        with self.database.transaction('ws_a') as cursor:
            cursor.execute("SELECT count(*) AS n FROM case_audit WHERE action='request_check' AND created_at>now()-interval '1 minute'")
            remaining=max(0,6-cursor.fetchone()['n'])
        for _ in range(remaining):
            _,_,url=self.fixture()
            self.assertEqual(self.http.post(url+'/check',headers=owner).status_code,202)
        _,_,url=self.fixture()
        availability=self.http.get(url+'/check-availability').json()
        self.assertFalse(availability['allowed'])
        self.assertGreater(availability['retry_after_seconds'],0)
        blocked=self.http.post(url+'/check',headers=owner)
        self.assertEqual(blocked.status_code,429)
        self.assertLessEqual(abs(int(blocked.headers['Retry-After'])-availability['retry_after_seconds']),1)


if __name__=='__main__':
    try:
        subprocess.run(['docker','compose','stop',*WORKERS],cwd=ROOT,check=True,capture_output=True)
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(OperatorChecks)
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        subprocess.run(['docker','compose','start',*WORKERS],cwd=ROOT,check=True,capture_output=True)
    sys.exit(0 if result.wasSuccessful() else 1)
