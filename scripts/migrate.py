"""Apply checksum-verified, transactional SQL migrations with an advisory lock."""

import argparse
import hashlib
import os
from pathlib import Path

import psycopg2


def migrate(service: str, url: str):
    directory = Path(__file__).resolve().parents[1] / "infra/migrations" / service
    if service not in {"console", "reference", "simulator"}:
        raise ValueError("Unknown migration service")
    with psycopg2.connect(url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(71001)")
            cursor.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, digest text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            for path in sorted(directory.glob("*.sql")):
                statement = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(statement.encode()).hexdigest()
                cursor.execute("SELECT digest FROM schema_migrations WHERE version=%s", (path.name,))
                previous = cursor.fetchone()
                if previous:
                    if previous[0] != checksum:
                        raise ValueError("An applied migration changed; add a new migration instead")
                    continue
                cursor.execute(statement)
                cursor.execute("INSERT INTO schema_migrations VALUES (%s,%s,now())", (path.name, checksum))
            cursor.execute(f"GRANT SELECT ON schema_migrations TO {service}_runtime")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("console", "reference", "simulator"))
    args = parser.parse_args()
    migrate(args.service, os.environ["ADMIN_DATABASE_URL"])
    print(f"{args.service} migrations applied.")
