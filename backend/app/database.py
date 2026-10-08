"""Bounded PostgreSQL connections and transaction-local tenant context."""

from contextlib import contextmanager
import hashlib

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Database:
    def __init__(self, url: str):
        self.pool = ThreadedConnectionPool(1, 8, url, connect_timeout=5)
        try:
            with self.transaction() as cursor:
                cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                role = cursor.fetchone()
                if role["rolsuper"] or role["rolbypassrls"]:
                    raise ValueError("Application connections cannot use privileged PostgreSQL roles")
                cursor.execute("SELECT to_regclass('public.schema_migrations') AS table_name")
                if cursor.fetchone()["table_name"] is None:
                    raise ValueError("Apply database migrations before starting the application")
        except Exception:
            self.pool.closeall()
            raise

    @contextmanager
    def transaction(self, workspace: str = "", subject: str = ""):
        connection = self.pool.getconn()
        try:
            with connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        "SELECT set_config('app.workspace', %s, true), set_config('app.subject', %s, true)",
                        (workspace, subject),
                    )
                    yield cursor
        finally:
            # Commit/rollback resets SET LOCAL values before this connection is reused.
            self.pool.putconn(connection)

    def close(self):
        self.pool.closeall()
