import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class SafeValidationTests(unittest.TestCase):
    def test_untrusted_values_and_field_names_are_not_reflected(self):
        # No lifespan/database needed: validation precedes endpoint invocation.
        for service, path in [('reference', '/demo/checkouts'),
                              ('console', '/api/purchases'),
                              ('simulator', '/internal/payments')]:
            with self.subTest(service=service):
                client = TestClient(create_app(service))
                canary = 'sk_live_PRIVATE_CANARY'
                response = client.post(path, json={canary: canary, 'purchase_id': canary + '!'},
                                       headers={'Authorization': 'Bearer ' + canary})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn(canary, response.text)
                self.assertEqual(response.json()['detail'], 'Invalid request')

    def test_console_security_headers(self):
        response = TestClient(create_app('console')).get('/health/live')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
