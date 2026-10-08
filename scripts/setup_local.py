"""Generate ignored local development secrets once; do not print their values."""

from pathlib import Path
import secrets


root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    raise SystemExit(".env already exists; preserving its credentials.")
names = ["POSTGRES_PASSWORD", "CONSOLE_DB_PASSWORD", "REFERENCE_DB_PASSWORD", "SIMULATOR_DB_PASSWORD", "DEMO_LOGIN_KEY"]
names += [f"WORKSPACE_{letter}_{purpose}_KEY" for letter in ("A", "B") for purpose in ("REGISTRATION", "ADAPTER", "PROVIDER", "CHECKOUT", "WEBHOOK")]
path.write_text("# Generated local-only secrets. Never commit this file.\n" + "\n".join(f"{name}={secrets.token_hex(32)}" for name in names) + "\n", encoding="utf-8")
print("Created ignored .env with distinct local development credentials.")
