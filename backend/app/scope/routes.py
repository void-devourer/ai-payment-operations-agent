"""Scope & Pay routes. All operator writes use the existing actor/CSRF checks."""
from datetime import UTC, datetime, timedelta
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import Json

from ..contracts import Identifier
from ..database import digest
from ..security import actor
from .models import (AnalysisInput, BriefInput, DecisionInput, Empty, InvoiceInput,
    MessageInput, ProjectInput, ProposalEdit, ProposalInput, ShareInput, connection_digest, proposal_digest)
from . import store

router = APIRouter()
BASE = '/api/workspaces/{workspace}/scope'


def tx(request, workspace, *, write=False, recent=False):
    subject = actor(request, workspace, write=write, recent=recent)
    return request.app.state.database.transaction(workspace, subject)


@router.get(BASE + '/config')
def configuration(workspace: Identifier, request: Request):
    actor(request, workspace)
    from ..scope_ai import configuration as ai_configuration
    config = ai_configuration()
    return {'analysis': config, 'invoice': {'mode': 'paypal_sandbox' if workspace in request.app.state.settings.paypal else 'local'},
            'sample_available': True}


@router.get(BASE + '/projects')
def projects(workspace: Identifier, request: Request):
    with tx(request, workspace) as cursor:
        cursor.execute('''SELECT project_id,name,client_name,client_email,brief,brief_revision,base_amount_minor,
            currency,demo,created_at FROM scope_projects ORDER BY created_at DESC,project_id LIMIT 100''')
        return {'data': cursor.fetchall()}


def create(cursor, workspace, body, demo=False):
    project_id = store.identifier('sp')
    cursor.execute('''INSERT INTO scope_projects(workspace_id,project_id,name,client_name,client_email,brief,base_amount_minor,currency,demo)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
        (workspace, project_id, body.name, body.client_name, body.client_email, body.brief, body.base_amount_minor, body.currency, demo))
    store.event(cursor, workspace, project_id, 'project_created', 'Sample project created' if demo else 'Project brief saved')
    return project_id


@router.post(BASE + '/projects')
def create_project(workspace: Identifier, body: ProjectInput, request: Request):
    with tx(request, workspace, write=True) as cursor:
        project_id = create(cursor, workspace, body)
        return store.detail(cursor, project_id)


@router.post(BASE + '/demo')
def demo(workspace: Identifier, request: Request):
    from ..scope_ai import SAMPLE_BRIEF, SAMPLE_MESSAGES
    with tx(request, workspace, write=True) as cursor:
        # Serialize the singleton sample creation even when no project exists yet.
        cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('scope-demo:' + workspace,))
        cursor.execute('SELECT project_id FROM scope_projects WHERE demo')
        existing = cursor.fetchone()
        if existing:
            return store.detail(cursor, existing['project_id'])
        project_id = create(cursor, workspace, ProjectInput(name='Website project · sample', client_name='Alex Morgan',
            client_email='alex@example.test', brief=SAMPLE_BRIEF, base_amount_minor=50000), demo=True)
        for text in SAMPLE_MESSAGES:
            cursor.execute('INSERT INTO scope_messages(workspace_id,project_id,message_id,text,text_digest) VALUES (%s,%s,%s,%s,%s)',
                           (workspace, project_id, store.identifier('msg'), text, digest(text)))
        return store.detail(cursor, project_id)


@router.get(BASE + '/projects/{project_id}')
def project_detail(workspace: Identifier, project_id: Identifier, request: Request):
    with tx(request, workspace) as cursor:
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/brief')
def update_brief(workspace: Identifier, project_id: Identifier, body: BriefInput, request: Request):
    with tx(request, workspace, write=True) as cursor:
        row = store.project(cursor, project_id, lock=True)
        if row['brief_revision'] != body.expected_revision:
            raise HTTPException(409, 'The brief changed; reload before editing')
        if row['brief'] == body.brief:
            return store.detail(cursor, project_id)
        cursor.execute('SELECT 1 FROM scope_invoices WHERE project_id=%s LIMIT 1', (project_id,))
        if cursor.fetchone():
            raise HTTPException(409, 'This brief is preserved by an invoice; create a separate project for a replacement agreement')
        cursor.execute('UPDATE scope_projects SET brief=%s,brief_revision=brief_revision+1 WHERE project_id=%s', (body.brief, project_id))
        cursor.execute("UPDATE scope_proposals SET status='superseded',accepted_by=NULL,accepted_at=NULL WHERE project_id=%s", (project_id,))
        cursor.execute('UPDATE scope_shares SET revoked_at=now() WHERE project_id=%s AND revoked_at IS NULL', (project_id,))
        store.event(cursor, workspace, project_id, 'brief_revised', 'Brief revised; previous change approvals and links are no longer current')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/messages')
def add_message(workspace: Identifier, project_id: Identifier, body: MessageInput, request: Request):
    with tx(request, workspace, write=True) as cursor:
        store.project(cursor, project_id, lock=True)
        cursor.execute('SELECT message_id FROM scope_messages WHERE project_id=%s AND text_digest=%s', (project_id, digest(body.text)))
        if cursor.fetchone():
            return store.detail(cursor, project_id)
        cursor.execute('SELECT count(*) AS count FROM scope_messages WHERE project_id=%s', (project_id,))
        if cursor.fetchone()['count'] >= 50:
            raise HTTPException(409, 'This project has reached the 50-message limit')
        cursor.execute('INSERT INTO scope_messages(workspace_id,project_id,message_id,text,text_digest) VALUES (%s,%s,%s,%s,%s)',
                       (workspace, project_id, store.identifier('msg'), body.text, digest(body.text)))
        store.event(cursor, workspace, project_id, 'message_added', 'Source message added')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/analysis')
def analyze(workspace: Identifier, project_id: Identifier, body: AnalysisInput, request: Request):
    from ..scope_ai import AnalysisError, analyze as ai_analyze, configuration as ai_configuration, sample_review
    with tx(request, workspace, write=True) as cursor:
        row = store.project(cursor, project_id)
        source = store.messages(cursor, project_id)
        snapshot = store.source_digest(row, source)
        if body.mode == 'sample' and not row['demo']:
            raise HTTPException(409, 'Sample review is only available for the unchanged sample project')
        if body.mode != 'sample':
            if ai_configuration()['mode'] != body.mode:
                raise HTTPException(503, 'The requested AI provider is not configured; check the server-side key and model')
            # Reserve before the external call. Failures and process loss still
            # consume the reservation; concurrent requests cannot evade quotas.
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('scope-analysis:' + workspace,))
            cursor.execute('''SELECT count(*) AS count,max(created_at) FILTER(WHERE project_id=%s) AS project_last,
                min(created_at) AS oldest FROM scope_analysis_requests WHERE created_at>now()-interval '1 minute' ''', (project_id,))
            budget = cursor.fetchone()
            now = datetime.now(UTC)
            seconds = 0
            if budget['project_last']:
                seconds = max(0, int((budget['project_last'] + timedelta(seconds=30) - now).total_seconds()) + 1)
            if budget['count'] >= 6:
                seconds = max(seconds, int((budget['oldest'] + timedelta(minutes=1) - now).total_seconds()) + 1)
            if seconds:
                raise HTTPException(429, 'Conversation reviews are limited to one per project every 30 seconds and six per workspace per minute', headers={'Retry-After': str(seconds)})
            cursor.execute('INSERT INTO scope_analysis_requests(workspace_id,project_id,request_id) VALUES (%s,%s,%s)',
                           (workspace, project_id, store.identifier('ar')))
    try:
        result = sample_review(row['brief'], source) if body.mode == 'sample' else ai_analyze(row['brief'], source, http=request.app.state.http)
    except AnalysisError as error:
        status = 422 if error.code in ('analysis_input_invalid', 'analysis_input_budget') else 503
        raise HTTPException(status if body.mode != 'sample' else 409, error.code) from None
    with tx(request, workspace, write=True) as cursor:
        current = store.project(cursor, project_id, lock=True)
        if snapshot != store.source_digest(current, store.messages(cursor, project_id)):
            raise HTTPException(409, 'The brief or messages changed during review; run review again')
        for candidate in result['candidates']:
            store.evidence(cursor, project_id, candidate['evidence'])
        cursor.execute('''INSERT INTO scope_analyses(workspace_id,project_id,analysis_id,brief_revision,source_digest,mode,summary,candidates)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
            (workspace, project_id, store.identifier('an'), row['brief_revision'], snapshot, result['mode'], result['summary'], Json(result['candidates'])))
        store.event(cursor, workspace, project_id, 'analysis_completed', 'Curated sample review completed' if body.mode == 'sample' else 'AI conversation review completed; interpretation requires your review')
        return store.detail(cursor, project_id)


def proposal_values(cursor, row, body, version):
    if row['brief_revision'] != body.expected_brief_revision:
        raise HTTPException(409, 'This proposal uses an older brief; reload before saving')
    payload = body.model_dump()
    store.evidence(cursor, row['project_id'], payload['evidence'])
    return payload, proposal_digest(row, payload, version)


@router.post(BASE + '/projects/{project_id}/proposals')
def create_proposal(workspace: Identifier, project_id: Identifier, body: ProposalInput, request: Request):
    with tx(request, workspace, write=True) as cursor:
        row = store.project(cursor, project_id, lock=True)
        cursor.execute('SELECT count(*) AS count FROM scope_proposals WHERE project_id=%s', (project_id,))
        if cursor.fetchone()['count'] >= 100:
            raise HTTPException(409, 'This project has reached the 100-proposal limit')
        values, fingerprint = proposal_values(cursor, row, body, 1)
        cursor.execute('''INSERT INTO scope_proposals(workspace_id,project_id,proposal_id,title,description,amount_minor,currency,
            brief_revision,status,proposal_digest,evidence) VALUES (%s,%s,%s,%s,%s,%s,'usd',%s,'draft',%s,%s)''',
            (workspace, project_id, store.identifier('cp'), body.title, body.description, body.amount_minor,
             row['brief_revision'], fingerprint, Json(values['evidence'])))
        store.event(cursor, workspace, project_id, 'proposal_created', 'Change proposal drafted for client review')
        return store.detail(cursor, project_id)


@router.patch(BASE + '/projects/{project_id}/proposals/{proposal_id}')
def edit_proposal(workspace: Identifier, project_id: Identifier, proposal_id: Identifier, body: ProposalEdit, request: Request):
    with tx(request, workspace, write=True) as cursor:
        row = store.project(cursor, project_id, lock=True)
        proposal = store.proposal(cursor, project_id, proposal_id, lock=True)
        if proposal['version'] != body.expected_version:
            raise HTTPException(409, 'The proposal changed; reload before editing')
        store.invoiced(cursor, proposal_id)
        values, fingerprint = proposal_values(cursor, row, body, proposal['version'] + 1)
        store.revoke(cursor, proposal_id)
        cursor.execute('''UPDATE scope_proposals SET title=%s,description=%s,amount_minor=%s,version=version+1,
            brief_revision=%s,status='draft',proposal_digest=%s,evidence=%s,accepted_by=NULL,accepted_at=NULL WHERE proposal_id=%s''',
            (body.title, body.description, body.amount_minor, row['brief_revision'], fingerprint, Json(values['evidence']), proposal_id))
        store.event(cursor, workspace, project_id, 'proposal_revised', 'Change proposal revised; previous link and approval revoked')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/proposals/{proposal_id}/share')
def share(workspace: Identifier, project_id: Identifier, proposal_id: Identifier, body: ShareInput, request: Request):
    with tx(request, workspace, write=True, recent=True) as cursor:
        row = store.project(cursor, project_id, lock=True)
        proposal = store.proposal(cursor, project_id, proposal_id, lock=True)
        if proposal['version'] != body.expected_version or proposal['brief_revision'] != row['brief_revision'] or proposal['status'] == 'superseded':
            raise HTTPException(409, 'The proposal is no longer current')
        store.invoiced(cursor, proposal_id)
        if proposal['status'] == 'accepted':
            raise HTTPException(409, 'This proposal is already accepted; edit it to request a new acceptance')
        token = secrets.token_urlsafe(32)
        token_hash = digest(token)
        expires = datetime.now(UTC) + timedelta(days=7)
        store.revoke(cursor, proposal_id)
        cursor.execute('INSERT INTO scope_capability_directory(token_digest,workspace_id) VALUES (%s,%s)', (token_hash, workspace))
        snapshot = {'brief': row['brief'], 'project_name': row['name'], 'client_name': row['client_name'],
            'proposal': {key: proposal[key] for key in ('proposal_id','title','description','amount_minor','currency','version',
                'brief_revision','proposal_digest','evidence')}}
        cursor.execute('''INSERT INTO scope_shares(workspace_id,project_id,proposal_id,token_digest,proposal_version,proposal_digest,proposal_snapshot,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''', (workspace, project_id, proposal_id, token_hash, proposal['version'], proposal['proposal_digest'], Json(snapshot), expires))
        cursor.execute("UPDATE scope_proposals SET status='shared' WHERE proposal_id=%s", (proposal_id,))
        store.event(cursor, workspace, project_id, 'proposal_shared', 'Client review link created; expires in seven days')
        return {'share_url': '/#/review/' + token, 'expires_at': expires, 'proposal_id': proposal_id, 'proposal_version': proposal['version']}


@router.post(BASE + '/projects/{project_id}/proposals/{proposal_id}/share/revoke')
def revoke_share(workspace: Identifier, project_id: Identifier, proposal_id: Identifier, body: Empty, request: Request):
    with tx(request, workspace, write=True) as cursor:
        store.project(cursor, project_id, lock=True)
        proposal = store.proposal(cursor, project_id, proposal_id, lock=True)
        cursor.execute('''UPDATE scope_shares SET revoked_at=now() WHERE proposal_id=%s AND revoked_at IS NULL
            RETURNING token_digest''', (proposal_id,))
        if cursor.fetchone():
            # Revoking a link is access control, not undoing an agreement.
            if proposal['status'] == 'shared':
                cursor.execute("UPDATE scope_proposals SET status='draft' WHERE proposal_id=%s", (proposal_id,))
            store.event(cursor, workspace, project_id, 'share_revoked', 'Client review link revoked')
        return store.detail(cursor, project_id)


def capability(request):
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer ') or len(authorization) != 50:
        raise HTTPException(404, 'Review link not found')
    token = authorization[7:]
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        raise HTTPException(404, 'Review link not found')
    hashed = digest(token)
    with request.app.state.database.transaction() as cursor:
        cursor.execute('SELECT workspace_id FROM scope_capability_directory WHERE token_digest=%s', (hashed,))
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, 'Review link not found')
    return row['workspace_id'], hashed


def review_records(cursor, hashed):
    # Project lock first everywhere, including public decisions, avoids edit/decision deadlocks.
    cursor.execute('SELECT project_id FROM scope_shares WHERE token_digest=%s', (hashed,))
    route = cursor.fetchone()
    if route is None:
        raise HTTPException(404, 'Review link not found')
    row = store.project(cursor, route['project_id'], lock=True)
    cursor.execute('SELECT * FROM scope_shares WHERE token_digest=%s FOR UPDATE', (hashed,))
    link = cursor.fetchone()
    if link['revoked_at'] or link['expires_at'] <= datetime.now(UTC):
        raise HTTPException(410, 'This review link expired or was replaced; request a new link')
    proposal = store.proposal(cursor, row['project_id'], link['proposal_id'], lock=True)
    if proposal['version'] != link['proposal_version'] or proposal['proposal_digest'] != link['proposal_digest'] or proposal['brief_revision'] != row['brief_revision'] or proposal['status'] == 'superseded':
        raise HTTPException(410, 'This proposal changed; request its current review link')
    return row, proposal, link


@router.get('/api/scope/review')
def review(request: Request):
    workspace, hashed = capability(request)
    with request.app.state.database.transaction(workspace) as cursor:
        row, proposal, link = review_records(cursor, hashed)
        exposed = {key: proposal[key] for key in ('proposal_id', 'title', 'description', 'amount_minor', 'currency', 'version',
                   'brief_revision', 'status', 'proposal_digest', 'evidence', 'accepted_by', 'accepted_at', 'created_at')}
        return {'project_name': row['name'], 'client_name': row['client_name'], 'brief': row['brief'],
                'proposal': exposed, 'expires_at': link['expires_at']}


@router.post('/api/scope/review/decision')
def decide(body: DecisionInput, request: Request):
    workspace, hashed = capability(request)
    with request.app.state.database.transaction(workspace) as cursor:
        row, proposal, link = review_records(cursor, hashed)
        if body.proposal_version != proposal['version'] or body.proposal_digest != proposal['proposal_digest']:
            raise HTTPException(409, 'The exact current proposal must be confirmed')
        if link['decision']:
            if link['decision'] != body.decision or link['decision_name'] != body.name:
                raise HTTPException(409, 'A different decision has already been recorded')
            return {'status': link['decision']}
        cursor.execute('UPDATE scope_shares SET decision=%s,decision_name=%s,decided_at=now() WHERE token_digest=%s',
                       (body.decision, body.name, hashed))
        cursor.execute('UPDATE scope_proposals SET status=%s,accepted_by=%s,accepted_at=CASE WHEN %s THEN now() ELSE NULL END WHERE proposal_id=%s',
                       (body.decision, body.name if body.decision == 'accepted' else None, body.decision == 'accepted', proposal['proposal_id']))
        store.event(cursor, workspace, row['project_id'], 'client_' + body.decision,
                    'Client explicitly accepted this version and amount' if body.decision == 'accepted' else 'Client declined this change proposal')
        return {'status': body.decision}


@router.post(BASE + '/projects/{project_id}/invoices')
def queue_invoice(workspace: Identifier, project_id: Identifier, body: InvoiceInput, request: Request):
    with tx(request, workspace, write=True, recent=True) as cursor:
        row = store.project(cursor, project_id, lock=True)
        proposal = store.proposal(cursor, project_id, body.proposal_id, lock=True)
        if proposal['status'] != 'accepted' or proposal['brief_revision'] != row['brief_revision']:
            raise HTTPException(409, 'The client must explicitly accept the current proposal first')
        cursor.execute('SELECT provider FROM scope_invoices WHERE proposal_id=%s', (body.proposal_id,))
        existing = cursor.fetchone()
        if existing:
            if existing['provider'] != body.mode:
                raise HTTPException(409, 'A logical invoice already exists using a different provider')
            return store.detail(cursor, project_id)
        if body.mode == 'paypal_sandbox' and workspace not in request.app.state.settings.paypal:
            raise HTTPException(503, 'PayPal sandbox is not configured for this workspace')
        binding = connection_digest(request.app.state.settings.paypal[workspace]) if body.mode == 'paypal_sandbox' else None
        invoice_id = store.identifier('inv')
        payload = {'invoice_id': invoice_id, 'recipient_email': row['client_email'], 'client_name': row['client_name'],
            'project_name': row['name'], 'title': proposal['title'], 'description': proposal['description'],
            'amount_minor': proposal['amount_minor'], 'currency': proposal['currency']}
        cursor.execute('''INSERT INTO scope_invoices(workspace_id,project_id,invoice_id,proposal_id,proposal_version,proposal_digest,
            provider,provider_connection_digest,status,amount_minor,currency,payload) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s)''',
            (workspace, project_id, invoice_id, proposal['proposal_id'], proposal['version'], proposal['proposal_digest'],
             body.mode, binding, proposal['amount_minor'], proposal['currency'], Json(payload)))
        cursor.execute("INSERT INTO scope_invoice_jobs(workspace_id,invoice_id,state) VALUES (%s,%s,'queued')", (workspace, invoice_id))
        store.event(cursor, workspace, project_id, 'invoice_queued', 'Local demo invoice queued' if body.mode == 'local' else 'PayPal sandbox draft queued; no invoice email will be sent')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/invoices/{invoice_id}/refresh')
def refresh_invoice(workspace: Identifier, project_id: Identifier, invoice_id: Identifier, body: Empty, request: Request):
    from ..scope_invoicing import InvoiceError, read_invoice
    with tx(request, workspace, write=True) as cursor:
        store.project(cursor, project_id)
        cursor.execute('SELECT * FROM scope_invoices WHERE project_id=%s AND invoice_id=%s', (project_id, invoice_id))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, 'Invoice not found')
        if row['provider'] == 'local':
            return store.detail(cursor, project_id)
        if not row['provider_invoice_id']:
            raise HTTPException(409, 'No confirmed PayPal invoice reference is available; do not create another invoice')
    connection = request.app.state.settings.paypal.get(workspace)
    if connection is None:
        raise HTTPException(503, 'PayPal sandbox is not configured for this workspace')
    if connection_digest(connection) != row['provider_connection_digest']:
        raise HTTPException(409, 'PayPal seller connection changed; review the original invoice binding')
    try:
        result = read_invoice(connection, request.app.state.http, row['provider_invoice_id'], row['payload'])
    except InvoiceError as error:
        raise HTTPException(503, error.code) from None
    with tx(request, workspace, write=True) as cursor:
        store.project(cursor, project_id, lock=True)
        cursor.execute('SELECT * FROM scope_invoices WHERE invoice_id=%s FOR UPDATE', (invoice_id,))
        current = cursor.fetchone()
        if current['provider_invoice_id'] != row['provider_invoice_id'] or current['status'] == 'creating' or current['updated_at'] != row['updated_at']:
            raise HTTPException(409, 'Invoice state changed; reload before refreshing')
        if result['provider_invoice_id'] != row['provider_invoice_id'] or result['amount_minor'] != row['amount_minor'] or result['currency'] != row['currency']:
            raise HTTPException(502, 'PayPal invoice identity or amount did not match')
        if current['status'] == 'paid' and result['status'] != 'paid':
            raise HTTPException(409, 'A conflicting payment state requires review')
        # A draft read cannot prove that an earlier uncertain activation failed.
        # Retain the block until a confirmed payable/paid result resolves it.
        unresolved = current['last_error'] == 'activation_outcome_unknown' and (result['status'] == 'draft' or result['status'] == 'unpaid' and not result['payment_url'])
        cursor.execute('UPDATE scope_invoices SET status=%s,payment_url=%s,last_error=%s,updated_at=now() WHERE invoice_id=%s',
                       ('outcome_unknown' if unresolved else result['status'], result['payment_url'],
                        'activation_outcome_unknown' if unresolved else None, invoice_id))
        store.event(cursor, workspace, project_id, 'invoice_refreshed', 'PayPal sandbox invoice status checked')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/invoices/{invoice_id}/activate')
def activate(workspace: Identifier, project_id: Identifier, invoice_id: Identifier, body: Empty, request: Request):
    with tx(request, workspace, write=True, recent=True) as cursor:
        store.project(cursor, project_id, lock=True)
        cursor.execute('SELECT * FROM scope_invoices WHERE project_id=%s AND invoice_id=%s FOR UPDATE', (project_id, invoice_id))
        invoice = cursor.fetchone()
        if invoice is None:
            raise HTTPException(404, 'Invoice not found')
        if invoice['provider'] != 'paypal_sandbox' or not invoice['provider_invoice_id']:
            raise HTTPException(409, 'Only a confirmed PayPal sandbox draft can be activated')
        cursor.execute('SELECT * FROM scope_invoice_jobs WHERE invoice_id=%s FOR UPDATE', (invoice_id,))
        job = cursor.fetchone()
        if job['operation'] == 'activate' and job['state'] in ('queued', 'leased'):
            return store.detail(cursor, project_id)
        if invoice['status'] != 'draft' or invoice['last_error'] == 'activation_outcome_unknown':
            raise HTTPException(409, 'Check the existing invoice outcome before enabling a payment link')
        connection = request.app.state.settings.paypal.get(workspace)
        if connection is None:
            raise HTTPException(503, 'PayPal sandbox is not configured for this workspace')
        if connection_digest(connection) != invoice['provider_connection_digest']:
            raise HTTPException(409, 'PayPal seller connection changed; review the original invoice binding')
        cursor.execute("UPDATE scope_invoice_jobs SET operation='activate',state='queued',lease_token=NULL,lease_until=NULL WHERE invoice_id=%s", (invoice_id,))
        cursor.execute("UPDATE scope_invoices SET status='creating',updated_at=now() WHERE invoice_id=%s", (invoice_id,))
        store.event(cursor, workspace, project_id, 'invoice_activation_queued', 'PayPal sandbox payment link activation queued; recipient and sender emails are disabled')
        return store.detail(cursor, project_id)


@router.post(BASE + '/projects/{project_id}/invoices/{invoice_id}/demo-pay')
def demo_pay(workspace: Identifier, project_id: Identifier, invoice_id: Identifier, body: Empty, request: Request):
    with tx(request, workspace, write=True) as cursor:
        store.project(cursor, project_id, lock=True)
        cursor.execute('SELECT provider,status FROM scope_invoices WHERE invoice_id=%s AND project_id=%s FOR UPDATE', (invoice_id, project_id))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, 'Invoice not found')
        if row['provider'] != 'local':
            raise HTTPException(409, 'Demo payment is only available on local simulated invoices')
        if row['status'] == 'paid':
            return store.detail(cursor, project_id)
        if row['status'] != 'unpaid':
            raise HTTPException(409, 'Wait until the local invoice has been created')
        cursor.execute("UPDATE scope_invoices SET status='paid',updated_at=now() WHERE invoice_id=%s", (invoice_id,))
        store.event(cursor, workspace, project_id, 'demo_payment', 'Simulated payment recorded; no money moved')
        return store.detail(cursor, project_id)
