"""Durable bounded sweeps of every registered purchase, independent of the inbox.

Progress describes scheduling coverage, not successful provider reads. A scan
never trusts event delivery, limits history to a recent created window, or grants
access. Newly registered rows after the cutoff are included in the next sweep.
"""

import uuid

from .jobs import enqueue

PAGE_SIZE=20
INTERVAL_SECONDS=60


def schedule_page(database,workspace,connection_id,*,force=False):
    with database.transaction(workspace) as cursor:
        # One scheduler per connection; the durable cursor and enqueues commit together.
        cursor.execute('SELECT connection_id FROM connections WHERE connection_id=%s FOR UPDATE', (connection_id,))
        if cursor.fetchone() is None:
            return None
        cursor.execute("SELECT * FROM reconciliation_runs WHERE connection_id=%s AND state='scanning' FOR UPDATE", (connection_id,))
        run=cursor.fetchone()
        if run is None:
            cursor.execute("""SELECT 1 FROM reconciliation_runs WHERE connection_id=%s
                AND finished_at>now()-%s*interval '1 second' LIMIT 1""", (connection_id,INTERVAL_SECONDS))
            if cursor.fetchone() and not force:
                return None
            cursor.execute("""INSERT INTO reconciliation_runs(workspace_id,run_id,connection_id,state)
                VALUES (%s,%s,%s,'scanning') RETURNING *""", (workspace,uuid.uuid4().hex,connection_id))
            run=cursor.fetchone()
        cursor.execute("""SELECT purchase_id FROM purchases WHERE connection_id=%s
            AND registered_at<=%s AND purchase_id>%s ORDER BY purchase_id LIMIT %s""",
            (connection_id,run['cutoff_at'],run['after_purchase_id'],PAGE_SIZE+1))
        page=cursor.fetchall()
        unbound=0
        for purchase in page[:PAGE_SIZE]:
            cursor.execute('SELECT payment_intent_id FROM payment_attempts WHERE purchase_id=%s ORDER BY payment_intent_id LIMIT 21', (purchase['purchase_id'],))
            attempts=cursor.fetchall()
            if not attempts or len(attempts)>20:
                unbound+=1
            elif attempts:
                # One job reads all trusted attempts; no need to enqueue N equivalent reads.
                enqueue(cursor,workspace,connection_id,attempts[0]['payment_intent_id'])
        complete=len(page)<=PAGE_SIZE
        cursor.execute("""UPDATE reconciliation_runs SET after_purchase_id=%s,
            scheduled_purchases=scheduled_purchases+%s,unbound_purchases=unbound_purchases+%s,
            state=%s,finished_at=CASE WHEN %s THEN now() ELSE NULL END WHERE run_id=%s RETURNING *""",
            (page[min(len(page),PAGE_SIZE)-1]['purchase_id'] if page else run['after_purchase_id'],
             min(len(page),PAGE_SIZE)-unbound,unbound,'scheduled' if complete else 'scanning',complete,run['run_id']))
        return dict(cursor.fetchone())
