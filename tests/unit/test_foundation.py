from datetime import UTC, datetime
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.app.config import PURPOSES, Settings
from backend.app.contracts import Checkout, Grant, PurchaseRegistration
from backend.app.reference import payload_digest


class FoundationContractTests(unittest.TestCase):
    def environment(self):
        values = {"APP_ENV": "development", "DATABASE_URL": "postgresql://user:private-password@localhost/db", "DEMO_LOGIN_KEY": "login-test-" + "a" * 40}
        for letter in ("A", "B"):
            for purpose in PURPOSES:
                values[f"WORKSPACE_{letter}_{purpose}_KEY"] = f"{letter}-{purpose}-" + "x" * 40
        return values

    def test_config_accepts_only_local_mode_and_postgres(self):
        for changes in ({"APP_ENV": "production"}, {"DATABASE_URL": "sqlite:///test.db"}, {"APP_ENV": ""}):
            with self.subTest(changes=changes), patch.dict(os.environ, self.environment() | changes, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env("console")

    def test_config_secrets_are_not_in_repr(self):
        with patch.dict(os.environ, self.environment(), clear=True):
            settings = Settings.from_env("console")
        self.assertNotIn("private-password", repr(settings))
        self.assertNotIn(settings.demo_login_key, repr(settings))

    def test_config_rejects_empty_short_and_shared_secrets(self):
        for value in ("", "short", self.environment()["DEMO_LOGIN_KEY"]):
            with self.subTest(value=value), patch.dict(os.environ, self.environment() | {"WORKSPACE_A_REGISTRATION_KEY": value}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env("console")

    def test_config_service_keys_have_only_required_purposes(self):
        with patch.dict(os.environ, self.environment(), clear=True):
            settings = Settings.from_env("console")
        self.assertEqual(set(settings.keys["ws_a"]), {"registration", "provider", "adapter", "webhook"})

    def test_service_urls_reject_remote_or_embedded_credentials(self):
        for url in ("http://example.com", "http://user:secret@console", "http://169.254.169.254", "http://console?token=secret"):
            with self.subTest(url=url), patch.dict(os.environ, self.environment() | {"CONSOLE_URL": url}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env("console")

    def registration(self):
        return dict(workspace_id="ws_a", purchase_id="p_a", customer_id="c_a", product_id="digital_pass", expected_amount_minor=2500, currency="usd", connection_id="sim_ws_a", provider_customer_id="c_a")

    def test_money_input_rejects_bool_float_and_zero(self):
        for amount in (True, 2500.0, 0, -1, "2500"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                PurchaseRegistration(**(self.registration() | {"expected_amount_minor": amount}))

    def test_request_contract_rejects_unknown_fields_and_path_traversal(self):
        for values in ({"amount_minor": 1}, {"customer_id": "../other"}, {"purchase_id": ".."}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Checkout(**(dict(purchase_id="p_a", customer_id="c_a") | values))

    def test_receipt_digest_is_order_independent_and_payload_bound(self):
        self.assertEqual(payload_digest({"operation": "op_a", "revision": 0}), payload_digest({"revision": 0, "operation": "op_a"}))
        self.assertNotEqual(payload_digest({"revision": 0}), payload_digest({"revision": 1}))

    def test_grant_expiry_requires_timezone(self):
        with self.assertRaises(ValidationError):
            Grant(operation_id="op", workspace_id="ws_a", purchase_id="p", customer_id="c", product_id="digital_pass", expected_revision=0, proposal_id="proposal", expires_at=datetime.now())
        value = Grant(operation_id="op", workspace_id="ws_a", purchase_id="p", customer_id="c", product_id="digital_pass", expected_revision=0, proposal_id="proposal", expires_at=datetime.now(UTC))
        self.assertIs(value.expires_at.tzinfo, UTC)
