"""Interrupt only the local console; verify fulfillment and registration recovery."""

from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_phase1 import local_environment


env = local_environment()
headers = {"Authorization": f"Bearer {env['WORKSPACE_A_CHECKOUT_KEY']}"}
adapter = {"Authorization": f"Bearer {env['WORKSPACE_A_ADAPTER_KEY']}"}
suffix = uuid.uuid4().hex[:16]
body = {"purchase_id": f"outage_{suffix}", "customer_id": f"customer_{suffix}"}
with httpx.Client(timeout=10, trust_env=False) as client:
    subprocess.run(["docker", "compose", "stop", "console"], cwd=ROOT, check=True, capture_output=True)
    try:
        client.post("http://127.0.0.1:8001/demo/checkouts", json=body, headers=headers).raise_for_status()
        client.post(f"http://127.0.0.1:8001/demo/checkouts/{body['purchase_id']}/pay", headers=headers).raise_for_status()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            access = client.get(f"http://127.0.0.1:8001/internal/access/{body['purchase_id']}", headers=adapter).json()
            if access["status"] == "active":
                break
            time.sleep(0.5)
        if access["status"] != "active" or access["revision"] != 1:
            raise RuntimeError("Normal fulfillment failed while the console was unavailable")
    finally:
        subprocess.run(["docker", "compose", "start", "console"], cwd=ROOT, check=True, capture_output=True)
    url = f"postgresql://reference_runtime:{env['REFERENCE_DB_PASSWORD']}@127.0.0.1:{env.get('POSTGRES_PORT', '15432')}/reference"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with psycopg2.connect(url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.workspace','ws_a',true)")
                cursor.execute("SELECT count(*) FROM registration_outbox WHERE purchase_id=%s AND state='sent'", (body["purchase_id"],))
                count = cursor.fetchone()[0]
        if count == 2:
            break
        time.sleep(1)
    if count != 2:
        raise RuntimeError("Durable purchase/attempt registration did not recover after restart")
print("Console outage: independent normal fulfillment and durable registration recovery passed.")
