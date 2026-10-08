"""Fail-closed local configuration; real identity/provider deployment comes later."""

from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


SERVICES = {"console", "reference", "simulator"}
PURPOSES = ("REGISTRATION", "ADAPTER", "PROVIDER", "CHECKOUT", "WEBHOOK")
REQUIRED = {
    "console": ("REGISTRATION", "PROVIDER", "ADAPTER", "WEBHOOK"),
    "reference": ("REGISTRATION", "ADAPTER", "PROVIDER", "CHECKOUT"),
    "simulator": ("PROVIDER", "WEBHOOK"),
}


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
        return cls(service, database_url, login_key, keys, console_url, simulator_url, reference_url=reference_url)
