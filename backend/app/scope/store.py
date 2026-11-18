"""Tenant-scoped scope records; callers own the transaction and project lock."""
import uuid

from fastapi import HTTPException

from .models import canonical_digest


def identifier(prefix):
    return prefix + '_' + uuid.uuid4().hex


def project(cursor, project_id, *, lock=False):
    cursor.execute('SELECT * FROM scope_projects WHERE project_id=%s' + (' FOR UPDATE' if lock else ''), (project_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, 'Project not found')
    return row


def proposal(cursor, project_id, proposal_id, *, lock=False):
    cursor.execute('SELECT * FROM scope_proposals WHERE project_id=%s AND proposal_id=%s' + (' FOR UPDATE' if lock else ''), (project_id, proposal_id))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, 'Change proposal not found')
    return row


def messages(cursor, project_id):
    cursor.execute('SELECT message_id,text,created_at FROM scope_messages WHERE project_id=%s ORDER BY created_at,message_id', (project_id,))
    return cursor.fetchall()


def source_digest(row, source):
    return canonical_digest({'brief': row['brief'], 'revision': row['brief_revision'],
                             'messages': [{'message_id': m['message_id'], 'text': m['text']} for m in source]})


def event(cursor, workspace, project_id, kind, text):
    cursor.execute('INSERT INTO scope_events(workspace_id,project_id,event_id,kind,text) VALUES (%s,%s,%s,%s,%s)',
                   (workspace, project_id, identifier('ev'), kind, text))


def detail(cursor, project_id):
    row = dict(project(cursor, project_id))
    row.pop('workspace_id')
    row['messages'] = messages(cursor, project_id)
    cursor.execute('''SELECT analysis_id,mode,summary,candidates,created_at FROM scope_analyses
        WHERE project_id=%s AND brief_revision=%s AND source_digest=%s ORDER BY created_at DESC LIMIT 1''',
        (project_id, row['brief_revision'], source_digest(row, row['messages'])))
    row['analysis'] = cursor.fetchone()
    cursor.execute('''SELECT proposal_id,title,description,amount_minor,currency,version,brief_revision,status,
        proposal_digest,evidence,accepted_by,accepted_at,created_at FROM scope_proposals WHERE project_id=%s ORDER BY created_at DESC,proposal_id''', (project_id,))
    row['proposals'] = cursor.fetchall()
    cursor.execute('''SELECT invoice_id,proposal_id,provider,provider_invoice_id,status,amount_minor,currency,
        payment_url,last_error,created_at FROM scope_invoices WHERE project_id=%s ORDER BY created_at DESC,invoice_id''', (project_id,))
    row['invoices'] = cursor.fetchall()
    cursor.execute('''SELECT proposal_snapshot,decision,decision_name,decided_at,created_at,revoked_at
        FROM scope_shares WHERE project_id=%s AND decision IS NOT NULL ORDER BY decided_at DESC,created_at DESC LIMIT 100''', (project_id,))
    row['agreements'] = cursor.fetchall()
    cursor.execute('SELECT event_id,kind,text,created_at FROM scope_events WHERE project_id=%s ORDER BY created_at DESC,event_id LIMIT 100', (project_id,))
    row['events'] = cursor.fetchall()
    return row


def evidence(cursor, project_id, source):
    references = {m['message_id']: m['text'] for m in messages(cursor, project_id)}
    for item in source:
        if item['message_id'] not in references or not item['quote'].strip() or item['quote'] not in references[item['message_id']]:
            raise HTTPException(422, 'Every evidence quote must match this project\'s source message')


def revoke(cursor, proposal_id):
    cursor.execute('UPDATE scope_shares SET revoked_at=now() WHERE proposal_id=%s AND revoked_at IS NULL', (proposal_id,))


def invoiced(cursor, proposal_id):
    cursor.execute('SELECT 1 FROM scope_invoices WHERE proposal_id=%s', (proposal_id,))
    if cursor.fetchone():
        raise HTTPException(409, 'An invoice already preserves this agreed scope; create a separate change proposal')
