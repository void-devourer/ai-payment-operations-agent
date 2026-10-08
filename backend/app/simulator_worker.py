"""Durable synthetic webhook delivery; fresh signatures on each delivery attempt."""

import hashlib
import hmac
import json
from pathlib import Path
import time
import uuid

import httpx

from .config import Settings
from .database import Database


def deliver(database,settings,client,workspace):
    with database.transaction(workspace) as cursor:
        cursor.execute("""UPDATE events SET delivery_state='dead',last_error='attempt_limit'
            WHERE delivery_attempts>=12 AND (delivery_state IN ('queued','retry_wait') OR
            (delivery_state='leased' AND lease_until<=now()))""")
        cursor.execute("""SELECT * FROM events WHERE delivery_attempts<12 AND
            ((delivery_state IN ('queued','retry_wait') AND due_at<=now()) OR
             (delivery_state='leased' AND lease_until<=now()))
            ORDER BY due_at,event_id FOR UPDATE SKIP LOCKED LIMIT 1""")
        event=cursor.fetchone()
        if event is None:
            return False
        token=uuid.uuid4().hex
        cursor.execute("""UPDATE events SET delivery_state='leased',delivery_attempts=delivery_attempts+1,
            lease_token=%s,lease_until=now()+interval '30 seconds' WHERE event_id=%s""", (token,event["event_id"]))
    raw=json.dumps(event["payload"],sort_keys=True,separators=(",",":")).encode()
    timestamp=str(int(time.time()))
    signature=hmac.new(settings.keys[workspace]["webhook"].encode(),timestamp.encode()+b"."+raw,hashlib.sha256).hexdigest()
    try:
        response=client.post(settings.console_url+f"/webhooks/simulator/sim_{workspace}",content=raw,
                             headers={"Content-Type":"application/json","Simulator-Signature":f"t={timestamp},v1={signature}"})
        success=response.status_code==200 and response.json().get("received") is True
        permanent=400<=response.status_code<500 and response.status_code!=429
        error="delivery_rejected" if permanent else "console_unavailable"
    except (httpx.RequestError,ValueError,AttributeError):
        success,permanent,error=False,False,"network_or_ack_error"
    state="sent" if success else "dead" if permanent or event["delivery_attempts"]+1>=12 else "retry_wait"
    with database.transaction(workspace) as cursor:
        cursor.execute("""UPDATE events SET delivery_state=%s,last_error=%s,lease_token=NULL,lease_until=NULL,
            due_at=now()+%s*interval '1 second' WHERE event_id=%s AND delivery_state='leased'
            AND lease_token=%s AND lease_until>clock_timestamp()""",
            (state,None if success else error,min(60,2**(event["delivery_attempts"]+1)),event["event_id"],token))
    return True


def main():
    marker=Path('/tmp/simulator-worker-heartbeat')
    marker.unlink(missing_ok=True)
    settings=Settings.from_env('simulator')
    database=Database(settings.database_url)
    try:
        with httpx.Client(timeout=5,trust_env=False) as client:
            while True:
                for workspace in settings.keys:
                    marker.touch()
                    deliver(database,settings,client,workspace)
                marker.touch()
                time.sleep(.25)
    finally:
        database.close()


if __name__=='__main__':
    main()
