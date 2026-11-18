"""Real HTTP session restoration and incorrect-credential recovery regressions."""
from pathlib import Path
import sys
import unittest
import httpx
import psycopg2
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.restore_drill import admin_url
from backend.app.database import digest


class SessionFlowTests(unittest.TestCase):
    def setUp(self):
        self.env=local_environment()
        self.http=httpx.Client(base_url='http://127.0.0.1:8000',trust_env=False,timeout=8)

    def tearDown(self):
        self.http.close()

    def login(self):
        response=self.http.post('/dev/sessions/owner_a',headers={'X-Demo-Login-Key':self.env['DEMO_LOGIN_KEY']})
        response.raise_for_status()
        return response.json()

    def age_session(self, column, interval):
        assert column in {'expires_at','authenticated_at'}
        assert interval in {'31 minutes','1 second'}
        with psycopg2.connect(admin_url(self.env,'console')) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE sessions SET {column}=now()-interval '{interval}' WHERE token_digest=%s",
                               (digest(self.http.cookies['payment_session']),))

    def test_restore_session_and_csrf_after_reload(self):
        signed_in=self.login()
        restored=self.http.get('/api/session')
        self.assertEqual(restored.status_code,200,'A valid browser cookie must restore the full session')
        self.assertEqual(restored.json()['csrf_token'],signed_in['csrf_token'])
        self.assertEqual(restored.json()['subject'],'owner_a')
        self.assertIn('Max-Age=604800',restored.headers['set-cookie'])
        self.assertEqual(self.http.get('/api/session').json()['csrf_token'],signed_in['csrf_token'])
        cookie=self.http.cookies['payment_session']
        logout=self.http.post('/api/workspaces/ws_a/sessions/revoke',headers={'X-CSRF-Token':restored.json()['csrf_token']})
        self.assertEqual(logout.status_code,204)
        self.assertEqual(self.http.get('/api/session').status_code,401)
        self.http.cookies.set('payment_session',cookie)
        self.assertEqual(self.http.get('/api/session').status_code,401,'Revoked cookies must not renew')

    def test_wrong_credentials_then_correct_login(self):
        bad=self.http.post('/dev/sessions/owner_a',headers={'X-Demo-Login-Key':'incorrect-demo-password'})
        self.assertEqual(bad.status_code,401)
        self.assertEqual(bad.json()['detail'],'Incorrect credentials')
        self.login()
        self.assertEqual(self.http.get('/api/session').status_code,200)

    def test_sensitive_confirmation_keeps_browsing_and_same_session(self):
        signed_in=self.login()
        cookie=self.http.cookies['payment_session']
        self.age_session('authenticated_at','31 minutes')
        restored=self.http.get('/api/session')
        self.assertEqual(restored.status_code,200)
        self.assertEqual(self.http.get('/api/workspaces/ws_a/cases').status_code,200)
        headers={'X-CSRF-Token':signed_in['csrf_token']}
        body={'reason':'Review exception','observation_id':'o_missing','fingerprint':'a'*64}
        url='/api/workspaces/ws_a/cases/c_missing/dismiss'
        self.assertEqual(self.http.post(url,json=body,headers=headers).status_code,428)
        confirm='/api/workspaces/ws_a/sessions/confirm'
        self.assertEqual(self.http.post(confirm,headers={'X-Demo-Login-Key':self.env['DEMO_LOGIN_KEY']}).status_code,403)
        bad={**headers,'X-Demo-Login-Key':'incorrect-demo-password'}
        self.assertEqual(self.http.post(confirm,headers=bad).json()['detail'],'Incorrect credentials')
        self.assertEqual(self.http.get('/api/session').status_code,200,'Wrong confirmation must not log out')
        good={**headers,'X-Demo-Login-Key':self.env['DEMO_LOGIN_KEY']}
        self.assertEqual(self.http.post(confirm,headers=good).status_code,200)
        self.assertEqual(self.http.cookies['payment_session'],cookie,'Confirmation must preserve queued approval ownership')
        self.assertEqual(self.http.post(url,json=body,headers=headers).status_code,404)

    def test_expired_cookie_cannot_be_restored(self):
        self.login()
        self.age_session('expires_at','1 second')
        self.assertEqual(self.http.get('/api/session').status_code,401)
        self.assertEqual(self.http.get('/api/workspaces').status_code,401)


if __name__=='__main__':
    unittest.main(verbosity=2)
