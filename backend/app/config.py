"""Fail-closed local configuration; real identity/provider deployment comes later."""

from dataclasses import dataclass, field
import os
import re
from urllib.parse import urlsplit


SERVICES = {"console", "reference", "simulator"}
PURPOSES = ("REGISTRATION", "ADAPTER", "PROVIDER", "CHECKOUT", "WEBHOOK")
REQUIRED = {
    "console": ("REGISTRATION", "PROVIDER", "ADAPTER", "WEBHOOK"),
    "reference": ("REGISTRATION", "ADAPTER", "PROVIDER", "CHECKOUT"),
    "simulator": ("PROVIDER", "WEBHOOK"),
}

STRIPE_API_VERSION = "2026-09-30.endive"


@dataclass(frozen=True)
class StripeConnection:
    account_id: str
    read_key: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    api_version: str = STRIPE_API_VERSION

    def __post_init__(self):
        if not re.fullmatch(r"acct_[A-Za-z0-9]{8,80}",self.account_id):
            raise ValueError("A sandbox account ID is required")
        if not re.fullmatch(r"(?:rk|sk)_test_[A-Za-z0-9]{20,256}",self.read_key):
            raise ValueError("Only account-managed Stripe test keys are supported")
        if not re.fullmatch(r"whsec_[A-Za-z0-9]{20,256}",self.webhook_secret):
            raise ValueError("A real Stripe destination signing secret is required")
        if self.api_version != STRIPE_API_VERSION:
            raise ValueError("Stripe API version does not match the pinned normalizer")


def stripe_connections_from_env():
    enabled=os.environ.get("STRIPE_ENABLED","0")
    if enabled not in {"0","1"}:
        raise ValueError("STRIPE_ENABLED must be 0 or 1")
    if enabled=="0":
        return {}
    result={}
    for letter in ("A","B"):
        prefix=f"STRIPE_WORKSPACE_{letter}_"
        if any(os.environ.get(prefix+suffix) for suffix in ("ACCOUNT_ID","READ_KEY","WEBHOOK_SECRET")):
            result[f"ws_{letter.lower()}"]=StripeConnection(
                os.environ.get(prefix+"ACCOUNT_ID",""),os.environ.get(prefix+"READ_KEY",""),
                os.environ.get(prefix+"WEBHOOK_SECRET",""),os.environ.get("STRIPE_API_VERSION",STRIPE_API_VERSION))
    if not result:
        raise ValueError("Stripe enabled without an account-managed sandbox connection")
    if len({item.account_id for item in result.values()})!=len(result):
        raise ValueError("Each workspace needs a distinct Stripe sandbox account")
    if len({item.webhook_secret for item in result.values()})!=len(result):
        raise ValueError("Each Stripe destination needs a distinct signing secret")
    return result


@dataclass(frozen=True)
class Settings:
    service: str
    database_url: str = field(repr=False)
    demo_login_key: str = field(repr=False)
    keys: dict[str, dict[str, str]] = field(repr=False)
    console_url: str = "http://console:8000"
    simulator_url: str = "http://simulator:8000"
    session_seconds: int = 3600
    reference_url: str = "http://reference:8000"
    stripe: dict[str, StripeConnection] = field(default_factory=dict,repr=False)

    @classmethod
    def from_env(cls, service: str):
        if service not in SERVICES:
            raise ValueError("Unknown service")
        if os.environ.get("APP_ENV") != "development":
            raise ValueError("Phase 1 local identities require APP_ENV=development")
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url.startswith("postgresql://"):
            raise ValueError("DATABASE_URL must select PostgreSQL")
        login_key = os.environ.get("DEMO_LOGIN_KEY", "")
        keys = {
            f"ws_{letter.lower()}": {
                purpose.lower(): os.environ.get(f"WORKSPACE_{letter}_{purpose}_KEY", "")
                for purpose in REQUIRED[service]
            }
            for letter in ("A", "B")
        }
        secrets = ([login_key] if service == "console" else []) + [value for values in keys.values() for value in values.values()]
        if any(len(secret) < 32 for secret in secrets) or len(set(secrets)) != len(secrets):
            raise ValueError("Distinct generated development keys of at least 32 characters required")
        console_url = os.environ.get("CONSOLE_URL", "http://console:8000")
        simulator_url = os.environ.get("SIMULATOR_URL", "http://simulator:8000")
        reference_url = os.environ.get("REFERENCE_URL", "http://reference:8000")
        for value in (console_url, simulator_url, reference_url):
            parsed = urlsplit(value)
            if parsed.scheme != "http" or parsed.hostname not in {
                "console", "simulator", "reference", "localhost", "127.0.0.1"
            } or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Phase 1 service URLs must use the local deployment allowlist")
        stripe=stripe_connections_from_env() if service=="console" else {}
        return cls(service, database_url, login_key, keys, console_url, simulator_url, reference_url=reference_url,stripe=stripe)
