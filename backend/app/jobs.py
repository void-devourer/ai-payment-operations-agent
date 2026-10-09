"""At-least-once read jobs, short transactions, and lease-fenced state changes."""

import random
import uuid

MAX_ATTEMPTS = 8
LEASE_SECONDS = 30


class ReadFailure(Exception):
    def __init__(self, code, retryable=True, delay=None):
        super().__init__(code)
        self.code, self.retryable, self.delay = code, retryable, delay


def enqueue(cursor, workspace, connection, intent):
    cursor.execute("""INSERT INTO jobs(workspace_id,job_id,connection_id,payment_intent_id)
        VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id,connection_id,payment_intent_id)
        WHERE state IN ('queued','leased','retry_wait') DO UPDATE
        SET request_seq=jobs.request_seq+1, updated_at=now()
        RETURNING job_id""", (workspace, uuid.uuid4().hex, connection, intent))
    return cursor.fetchone()["job_id"]


def claim(database, workspace, intent=None):
    with database.transaction(workspace) as cursor:
        # Exhausted crashed workers become visible dead jobs rather than looping forever.
        cursor.execute("""UPDATE jobs SET state='dead',last_error='attempt_limit',lease_token=NULL,
            lease_until=NULL,updated_at=now() WHERE attempts >= %s AND
            (state IN ('queued','retry_wait') OR (state='leased' AND lease_until<=now()))""", (MAX_ATTEMPTS,))
        cursor.execute("""SELECT * FROM jobs WHERE attempts < %s AND (%s IS NULL OR payment_intent_id=%s) AND
            ((state IN ('queued','retry_wait') AND due_at<=now()) OR
             (state='leased' AND lease_until<=now()))
            ORDER BY due_at,created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1""", (MAX_ATTEMPTS,intent,intent))
        job = cursor.fetchone()
        if job is None:
            return None
        token = uuid.uuid4().hex
        cursor.execute("""UPDATE jobs SET state='leased',attempts=attempts+1,claimed_seq=request_seq,
            lease_token=%s,lease_until=now()+interval '30 seconds',updated_at=now()
            WHERE job_id=%s RETURNING *""", (token,job["job_id"]))
        return dict(cursor.fetchone())


def lock_owned(cursor, job):
    cursor.execute("""SELECT * FROM jobs WHERE job_id=%s AND state='leased' AND
        lease_token=%s AND lease_until>clock_timestamp() FOR UPDATE""", (job["job_id"],job["lease_token"]))
    row = cursor.fetchone()
    if row is None:
        raise ReadFailure("lease_lost")
    return row


def heartbeat(database, job):
    with database.transaction(job["workspace_id"]) as cursor:
        lock_owned(cursor, job)
        cursor.execute("UPDATE jobs SET lease_until=clock_timestamp()+interval '30 seconds' WHERE job_id=%s", (job["job_id"],))


def finish(cursor, job):
    row = lock_owned(cursor, job)
    state = "queued" if row["request_seq"] != row["claimed_seq"] else "completed"
    cursor.execute("""UPDATE jobs SET state=%s,due_at=now(),attempts=0,last_error=NULL,
        lease_token=NULL,lease_until=NULL,updated_at=now() WHERE job_id=%s""", (state,job["job_id"]))


def fail(database, job, error):
    delay = error.delay if error.delay is not None else min(60,2 ** job["attempts"]) + random.uniform(0,1)
    with database.transaction(job["workspace_id"]) as cursor:
        try:
            lock_owned(cursor,job)
        except ReadFailure:
            return False
        state = "retry_wait" if error.retryable and job["attempts"] < MAX_ATTEMPTS else "dead"
        cursor.execute("""UPDATE jobs SET state=%s,due_at=now()+%s*interval '1 second',
            last_error=%s,lease_token=NULL,lease_until=NULL,updated_at=now() WHERE job_id=%s""",
            (state,max(0,min(300,delay)),error.code,job["job_id"]))
    return True


def reserve_request(database, workspace, connection):
    with database.transaction(workspace) as cursor:
        cursor.execute("""UPDATE connections SET next_request_at=clock_timestamp()+interval '250 milliseconds'
            WHERE connection_id=%s AND next_request_at<=clock_timestamp() RETURNING connection_id""", (connection,))
        return cursor.fetchone() is not None
