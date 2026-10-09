"""Read-only console backup; restore ONLY to a new, isolated scratch database.

Never replaces the running database. Dumps contain private operational data and
are stored under ignored .local. No scratch API/worker is started or configured.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment
from scripts.migrate import migrate


def admin_url(env, database):
    return f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@127.0.0.1:{env.get('POSTGRES_PORT', '15432')}/{database}"


def create_scratch(env):
    name = 'release_drill_' + uuid.uuid4().hex
    connection = psycopg2.connect(admin_url(env, 'postgres'), connect_timeout=5)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            cursor.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
            cursor.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO console_runtime').format(sql.Identifier(name)))
    finally:
        connection.close()
    return name


def drill():
    env = local_environment()
    scratch = create_scratch(env)
    output = ROOT / '.local' / 'restore-drill'
    output.mkdir(parents=True, exist_ok=True)
    backup = subprocess.run(['docker', 'compose', 'exec', '-T', 'postgres', 'pg_dump',
                             '-U', 'postgres', '-d', 'console', '--format=custom'],
                            cwd=ROOT, capture_output=True, check=True).stdout
    (output / (scratch + '.dump')).write_bytes(backup)
    subprocess.run(['docker', 'compose', 'exec', '-T', 'postgres', 'pg_restore',
                    '-U', 'postgres', '-d', scratch, '--exit-on-error'],
                   input=backup, cwd=ROOT, capture_output=True, check=True)
    # Pause before any runtime connection is opened. Restore sessions cannot be
    # reused to authorize effects. External target receipts remain authoritative.
    with psycopg2.connect(admin_url(env, scratch)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE execution_control SET enabled=false,reason='Isolated restore; review external outcomes before enabling'")
            cursor.execute('DELETE FROM sessions')
            cursor.execute('SELECT count(*) FROM repair_operations')
            operations = cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM repair_approvals')
            approvals = cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM schema_migrations')
            versions = cursor.fetchone()[0]
    migrate('console', admin_url(env, scratch))  # idempotent/checksummed
    result = {'scratch_database': scratch, 'backup_bytes': len(backup),
              'backup_sha256': hashlib.sha256(backup).hexdigest(),
              'operations_preserved': operations, 'approvals_preserved': approvals,
              'migration_count': versions, 'execution_enabled': False,
              'sessions_invalidated': True, 'services_started': False}
    (output / 'latest.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    try:
        print(json.dumps(drill(), indent=2))
    except Exception as error:
        # pg_restore stderr / connection failures may contain private data.
        print('Restore drill failed: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
