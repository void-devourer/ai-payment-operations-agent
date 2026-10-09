"""Payload-bound approval and durable, fenced application-access repair.

No payment-provider writes. Once dispatch may have begun, only receipt lookup is
allowed. Missing receipts never prove that a remote transaction had no effect.
"""

from datetime import UTC, datetime, timedelta
import hashlib
import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
import httpx
from psycopg2.extras import Json
from pydantic import BaseModel, ConfigDict, Field

from .cases import CASE_SELECT, Dismissal, present
from .contracts import Grant, Identifier
from .database import digest
from .detection.policy import POLICY_VERSION
from .evidence import collect
from .jobs import ReadFailure, claim, enqueue, fail
from .security import actor

router = APIRouter()
ACTIVE = ('queued', 'executing', 'verifying', 'outcome_unknown')
MAX_ATTEMPTS = 8


class ProposalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    payload_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: str = Field(pattern=r'^(approve|reject)$')
    reason: str = Field(min_length=5, max_length=1000)


def canonical_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def audit(cursor, workspace, case, subject, action, reason, fingerprint):
    cursor.execute('INSERT INTO case_audit(workspace_id,audit_id,case_id,subject,action,reason,fingerprint) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                   (workspace, uuid.uuid4().hex, case, subject, action, reason, fingerprint))


def locked_case(cursor, case_id):
    cursor.execute('SELECT purchase_id FROM cases WHERE case_id=%s', (case_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(404, 'Case not found')
    cursor.execute('SELECT * FROM evidence_heads WHERE purchase_id=%s FOR UPDATE', (row['purchase_id'],))
    cursor.fetchone()
    cursor.execute(CASE_SELECT + ' WHERE c.case_id=%s FOR UPDATE OF c', (case_id,))
    return cursor.fetchone()


def eligible(case):
    return (case['discrepancy_code'] == 'PAID_ACCESS_MISSING'
            and case['state'] in ('open', 'awaiting_approval')
            and case['policy_version'] == POLICY_VERSION
            and case['outcome'] == 'eligible' and present(case)['evidence_fresh'])


def has_active(cursor, purchase):
    cursor.execute('SELECT 1 FROM repair_operations WHERE purchase_id=%s AND state=ANY(%s)', (purchase, list(ACTIVE)))
    return cursor.fetchone() is not None


@router.post('/api/workspaces/{workspace}/cases/{case_id}/proposals')
def propose(workspace: Identifier, case_id: Identifier, body: Dismissal, request: Request):
    subject = actor(request, workspace, write=True)
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, 'A meaningful reason is required')
    with request.app.state.database.transaction(workspace, subject) as cursor:
        case = locked_case(cursor, case_id)
        if (not eligible(case) or case['latest_observation_id'] != body.observation_id
                or case['fingerprint'] != body.fingerprint or has_active(cursor, case['purchase_id'])):
            raise HTTPException(409, 'Repair unavailable; refresh evidence and review this case')
        cursor.execute("SELECT * FROM repair_proposals WHERE purchase_id=%s AND state='pending' FOR UPDATE", (case['purchase_id'],))
        old = cursor.fetchone()
        if old and old['expires_at'] > datetime.now(UTC) and old['fingerprint'] == case['fingerprint'] and old['case_id'] == case_id:
            return public_proposal(old)
        if old:
            cursor.execute("UPDATE repair_proposals SET state='superseded' WHERE proposal_id=%s", (old['proposal_id'],))
        cursor.execute('SELECT * FROM purchases WHERE purchase_id=%s', (case['purchase_id'],))
        purchase = cursor.fetchone()
        cursor.execute('SELECT facts FROM observations WHERE observation_id=%s', (body.observation_id,))
        facts = cursor.fetchone()['facts']
        proposal_id = uuid.uuid4().hex
        expires = datetime.now(UTC) + timedelta(minutes=10)
        payload = Grant(operation_id=uuid.uuid4().hex, workspace_id=workspace,
                        purchase_id=purchase['purchase_id'], customer_id=purchase['customer_id'],
                        product_id=purchase['product_id'], expected_revision=facts['access']['revision'],
                        proposal_id=proposal_id, expires_at=expires).model_dump(mode='json')
        cursor.execute('''INSERT INTO repair_proposals(workspace_id,proposal_id,case_id,purchase_id,created_by,
            observation_id,fingerprint,policy_version,payload,payload_digest,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
            (workspace, proposal_id, case_id, purchase['purchase_id'], subject, body.observation_id,
             body.fingerprint, POLICY_VERSION, Json(payload), canonical_digest(payload), expires))
        result = public_proposal(cursor.fetchone())
        cursor.execute("UPDATE cases SET state='awaiting_approval',updated_at=now() WHERE case_id=%s", (case_id,))
        audit(cursor, workspace, case_id, subject, 'propose', body.reason.strip(), body.fingerprint)
        return result


def public_proposal(row):
    # Session identity is never included in operator responses.
    return {key: row[key] for key in ('proposal_id', 'case_id', 'created_by', 'observation_id',
            'fingerprint', 'policy_version', 'payload', 'payload_digest', 'expires_at', 'state', 'created_at')}


@router.get('/api/workspaces/{workspace}/cases/{case_id}/repairs')
def history(workspace: Identifier, case_id: Identifier, request: Request):
    subject = actor(request, workspace)
    with request.app.state.database.transaction(workspace, subject) as cursor:
        cursor.execute('SELECT 1 FROM cases WHERE case_id=%s', (case_id,))
        if cursor.fetchone() is None:
            raise HTTPException(404, 'Case not found')
        cursor.execute('SELECT * FROM repair_proposals WHERE case_id=%s ORDER BY created_at DESC LIMIT 20', (case_id,))
        proposals = [public_proposal(row) for row in cursor.fetchall()]
        cursor.execute('''SELECT o.operation_id,o.proposal_id,o.state,o.attempts,o.last_error,o.receipt,
            o.verification_observation_id,o.updated_at FROM repair_operations o
            JOIN repair_proposals p USING(workspace_id,proposal_id) WHERE p.case_id=%s
            ORDER BY o.created_at DESC LIMIT 20''', (case_id,))
        operations = cursor.fetchall()
        cursor.execute('''SELECT a.subject,a.decision,a.reason,a.created_at,a.proposal_id FROM repair_approvals a
            JOIN repair_proposals p USING(workspace_id,proposal_id) WHERE p.case_id=%s
            ORDER BY a.created_at DESC LIMIT 20''', (case_id,))
        decisions = cursor.fetchall()
        cursor.execute('''SELECT a.kind,a.result,a.created_at,a.operation_id FROM repair_attempts a
            JOIN repair_operations o USING(workspace_id,operation_id)
            JOIN repair_proposals p USING(workspace_id,proposal_id) WHERE p.case_id=%s
            ORDER BY a.created_at DESC LIMIT 50''', (case_id,))
        return {'proposals': proposals, 'operations': operations, 'decisions': decisions, 'attempts': cursor.fetchall()}


@router.post('/api/workspaces/{workspace}/proposals/{proposal_id}/decisions')
def decide(workspace: Identifier, proposal_id: Identifier, body: ProposalDecision, request: Request):
    subject = actor(request, workspace, write=True)
    if len(body.reason.strip()) < 5:
        raise HTTPException(422, 'A meaningful reason is required')
    with request.app.state.database.transaction(workspace, subject) as cursor:
        cursor.execute('SELECT case_id FROM repair_proposals WHERE proposal_id=%s', (proposal_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, 'Proposal not found')
        case = locked_case(cursor, row['case_id'])
        cursor.execute('SELECT * FROM repair_proposals WHERE proposal_id=%s FOR UPDATE', (proposal_id,))
        proposal = cursor.fetchone()
        if proposal['payload_digest'] != body.payload_digest:
            raise HTTPException(409, 'Proposal payload changed')
        cursor.execute('SELECT * FROM repair_approvals WHERE proposal_id=%s', (proposal_id,))
        previous = cursor.fetchone()
        if previous:
            if previous['subject'] != subject or previous['decision'] != body.decision or previous['reason'] != body.reason.strip():
                raise HTTPException(409, 'A different decision already exists')
            return {'proposal_id': proposal_id, 'decision': previous['decision'], 'operation_id': proposal['payload']['operation_id'] if previous['decision'] == 'approve' else None}
        if proposal['state'] != 'pending' or proposal['expires_at'] <= datetime.now(UTC):
            raise HTTPException(409, 'Proposal expired or superseded')
        if body.decision == 'approve' and (not eligible(case) or proposal['fingerprint'] != case['fingerprint'] or has_active(cursor, case['purchase_id'])):
            raise HTTPException(409, 'Current facts no longer authorize this proposal')
        cursor.execute('INSERT INTO repair_approvals(workspace_id,proposal_id,subject,session_digest,decision,payload_digest,reason) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                       (workspace, proposal_id, subject, digest(request.cookies['payment_session']), body.decision, body.payload_digest, body.reason.strip()))
        cursor.execute('UPDATE repair_proposals SET state=%s WHERE proposal_id=%s',
                       ('approved' if body.decision == 'approve' else 'rejected', proposal_id))
        if body.decision == 'approve':
            cursor.execute('INSERT INTO repair_operations(workspace_id,operation_id,proposal_id,purchase_id) VALUES (%s,%s,%s,%s)',
                           (workspace, proposal['payload']['operation_id'], proposal_id, case['purchase_id']))
        cursor.execute('UPDATE cases SET state=%s,updated_at=now() WHERE case_id=%s',
                       ('repair_in_progress' if body.decision == 'approve' else 'open', case['case_id']))
        audit(cursor, workspace, case['case_id'], subject, body.decision, body.reason.strip(), proposal['fingerprint'])
        return {'proposal_id': proposal_id, 'decision': body.decision, 'operation_id': proposal['payload']['operation_id'] if body.decision == 'approve' else None}


def claim_repair(database, workspace):
    with database.transaction(workspace) as cursor:
        cursor.execute('''SELECT * FROM repair_operations WHERE state=ANY(%s) AND due_at<=now()
            AND (attempts<%s OR state IN ('queued','executing')) AND (lease_until IS NULL OR lease_until<=now())
            ORDER BY due_at,created_at FOR UPDATE SKIP LOCKED LIMIT 1''', (list(ACTIVE), MAX_ATTEMPTS))
        row = cursor.fetchone()
        if row is None:
            return None
        # A crashed dispatch is uncertain even if no network call actually occurred.
        state = 'outcome_unknown' if row['dispatch_started_at'] and not row['receipt'] else row['state']
        cursor.execute('''UPDATE repair_operations SET lease_token=%s,lease_until=now()+interval '30 seconds',
            attempts=attempts+1,state=%s,updated_at=now() WHERE operation_id=%s RETURNING *''',
            (uuid.uuid4().hex, state, row['operation_id']))
        return dict(cursor.fetchone())


def owned(cursor, operation):
    cursor.execute('''SELECT * FROM repair_operations WHERE operation_id=%s AND lease_token=%s
        AND lease_until>clock_timestamp() FOR UPDATE''', (operation['operation_id'], operation['lease_token']))
    row = cursor.fetchone()
    if row is None:
        raise ReadFailure('repair_lease_lost')
    return row


def attempt(cursor, operation, kind, result):
    cursor.execute('INSERT INTO repair_attempts(workspace_id,attempt_id,operation_id,lease_token,kind,result) VALUES (%s,%s,%s,%s,%s,%s)',
                   (operation['workspace_id'], uuid.uuid4().hex, operation['operation_id'], operation['lease_token'], kind, result))


def transition(database, operation, state, error=None, receipt=None, observation=None):
    with database.transaction(operation['workspace_id']) as cursor:
        owned(cursor, operation)
        cursor.execute('SELECT * FROM repair_proposals WHERE proposal_id=%s', (operation['proposal_id'],))
        proposal = cursor.fetchone()
        case = locked_case(cursor, proposal['case_id'])
        if state == 'succeeded' and (case['latest_observation_id'] != observation
                or not present(case)['evidence_fresh'] or case['outcome'] != 'healthy'):
            state, error = 'applied_not_recovered', 'verification_changed_before_recording'
        cursor.execute('''UPDATE repair_operations SET state=%s,last_error=%s,receipt=coalesce(%s,receipt),
            verification_observation_id=coalesce(%s,verification_observation_id),lease_token=NULL,lease_until=NULL,
            due_at=now()+interval '2 seconds',updated_at=now() WHERE operation_id=%s''',
            (state, error, Json(receipt) if receipt else None, observation, operation['operation_id']))
        case_state = {'outcome_unknown': 'outcome_unknown', 'verifying': 'repair_in_progress', 'queued': 'repair_in_progress',
                      'succeeded': 'resolved'}.get(state, 'awaiting_evidence' if error == 'verification_unavailable' else 'open')
        if case['state'] not in ('dismissed', 'resolved') or state == 'outcome_unknown':
            cursor.execute('UPDATE cases SET state=%s,updated_at=now() WHERE case_id=%s', (case_state, proposal['case_id']))
        attempt(cursor, operation, 'result', error or state)
        audit(cursor, operation['workspace_id'], proposal['case_id'], 'system', 'repair_result', error or state, proposal['fingerprint'])


def refresh_evidence(app, operation):
    workspace = operation['workspace_id']
    with app.state.database.transaction(workspace) as cursor:
        cursor.execute('SELECT * FROM purchases WHERE purchase_id=%s', (operation['purchase_id'],))
        purchase = cursor.fetchone()
        cursor.execute('SELECT payment_intent_id FROM payment_attempts WHERE purchase_id=%s ORDER BY payment_intent_id LIMIT 1', (operation['purchase_id'],))
        row = cursor.fetchone()
        if row is None:
            raise ReadFailure('binding_not_registered', False)
        intent = row['payment_intent_id']
        enqueue(cursor, workspace, purchase['connection_id'], intent)
    job = claim(app.state.database, workspace, intent=intent)
    if job is None:
        raise ReadFailure('evidence_read_in_progress')
    try:
        collect(app, job)
    except ReadFailure as error:
        fail(app.state.database, job, error)
        raise
    return intent


def valid_receipt(receipt, payload):
    if not isinstance(receipt, dict):
        return False
    fields = ('operation_id', 'workspace_id', 'purchase_id', 'customer_id', 'product_id')
    if any(receipt.get(key) != payload[key] for key in fields) or receipt.get('payload_digest') != canonical_digest(payload):
        return False
    result = receipt.get('result')
    revision = receipt.get('revision')
    return (result in ('granted', 'request_expired', 'access_precondition_conflict')
            and type(revision) is int and revision >= 0
            and (result != 'granted' or revision == payload['expected_revision'] + 1))


def target_read(app, operation, path):
    headers = {'Authorization': 'Bearer ' + app.state.settings.keys[operation['workspace_id']]['adapter']}
    # Configuration validates this fixed base; no operator-supplied URL or path.
    started = time.monotonic()
    with app.state.http.stream('GET', app.state.settings.reference_url + path, headers=headers, timeout=5) as response:
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw.extend(chunk)
            if len(raw) > 1024 * 1024 or time.monotonic() - started > 5:
                raise ReadFailure('target_response_budget')
        if response.status_code != 200:
            raise ReadFailure('receipt_unavailable')
        try:
            return json.loads(raw)
        except (ValueError, RecursionError):
            raise ReadFailure('invalid_receipt') from None


def execute_repair(app, operation):
    database, workspace = app.state.database, operation['workspace_id']
    with database.transaction(workspace) as cursor:
        current = owned(cursor, operation)
        cursor.execute('SELECT * FROM repair_proposals WHERE proposal_id=%s', (operation['proposal_id'],))
        proposal = cursor.fetchone()
    payload = proposal['payload']
    receipt = current['receipt']
    if current['dispatch_started_at'] and not receipt:
        with database.transaction(workspace) as cursor:
            owned(cursor, operation)
            attempt(cursor, operation, 'lookup', 'started')
        receipt = target_read(app, operation, '/internal/operations/' + operation['operation_id'])
        if not valid_receipt(receipt, payload):
            raise ReadFailure('receipt_binding_mismatch')
    elif not receipt:
        refresh_evidence(app, operation)
        with database.transaction(workspace) as cursor:
            owned(cursor, operation)
            case = locked_case(cursor, proposal['case_id'])
            cursor.execute('SELECT subject,session_digest FROM repair_approvals WHERE proposal_id=%s AND decision=\'approve\'', (proposal['proposal_id'],))
            approval = cursor.fetchone()
        with database.transaction(workspace, approval['subject']) as cursor:
            cursor.execute("SELECT 1 FROM memberships WHERE workspace_id=%s AND subject=%s AND active AND role IN ('owner','operator')", (workspace, approval['subject']))
            authorized = cursor.fetchone() is not None
            cursor.execute('SELECT 1 FROM sessions WHERE token_digest=%s AND subject=%s AND expires_at>now()', (approval['session_digest'], approval['subject']))
            authorized = authorized and cursor.fetchone() is not None
        if not authorized:
            transition(database, operation, 'blocked', 'approval_authority_revoked')
            return
        if (proposal['expires_at'] <= datetime.now(UTC) or proposal['policy_version'] != POLICY_VERSION
                or not present(case)['evidence_fresh'] or case['outcome'] != 'eligible'
                or case['fingerprint'] != proposal['fingerprint']
                or canonical_digest(payload) != proposal['payload_digest']):
            transition(database, operation, 'blocked', 'proposal_no_longer_eligible')
            return
        # Commit intent before the call. Reclaimed workers MUST perform lookup.
        with database.transaction(workspace, approval['subject']) as cursor:
            owned(cursor, operation)
            latest = locked_case(cursor, proposal['case_id'])
            if (latest['fingerprint'] != proposal['fingerprint'] or not present(latest)['evidence_fresh']
                    or latest['outcome'] != 'eligible' or proposal['expires_at'] <= datetime.now(UTC)
                    or proposal['policy_version'] != POLICY_VERSION):
                raise ReadFailure('evidence_changed_before_dispatch')
            cursor.execute("SELECT 1 FROM memberships WHERE workspace_id=%s AND subject=%s AND active AND role IN ('owner','operator')", (workspace, approval['subject']))
            member = cursor.fetchone()
            cursor.execute('SELECT 1 FROM sessions WHERE token_digest=%s AND subject=%s AND expires_at>now()', (approval['session_digest'], approval['subject']))
            if member is None or cursor.fetchone() is None:
                raise ReadFailure('approval_authority_revoked', False)
            cursor.execute("UPDATE repair_operations SET state='executing',dispatch_started_at=now(),lease_until=clock_timestamp()+interval '30 seconds' WHERE operation_id=%s", (operation['operation_id'],))
            attempt(cursor, operation, 'dispatch', 'started')
        headers = {'Authorization': 'Bearer ' + app.state.settings.keys[workspace]['adapter']}
        # Every response is subsequently checked against the primary receipt. A 5xx
        # can follow commit, so even known transport errors remain uncertain.
        started = time.monotonic()
        with app.state.http.stream('POST', app.state.settings.reference_url + '/internal/access-grants', json=payload, headers=headers, timeout=5) as response:
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1024 * 1024 or time.monotonic() - started > 5:
                    raise ReadFailure('target_response_budget')
        receipt = target_read(app, operation, '/internal/operations/' + operation['operation_id'])
        if not valid_receipt(receipt, payload):
            raise ReadFailure('receipt_binding_mismatch')
    if receipt['result'] != 'granted':
        transition(database, operation, 'conflict', receipt['result'], receipt)
        return
    with database.transaction(workspace) as cursor:
        owned(cursor, operation)
        cursor.execute("UPDATE repair_operations SET state='verifying',receipt=%s,lease_until=clock_timestamp()+interval '30 seconds' WHERE operation_id=%s", (Json(receipt), operation['operation_id']))
        attempt(cursor, operation, 'verify', 'started')
    refresh_evidence(app, operation)
    with database.transaction(workspace) as cursor:
        owned(cursor, operation)
        case = locked_case(cursor, proposal['case_id'])
        cursor.execute('SELECT facts FROM observations WHERE observation_id=%s', (case['latest_observation_id'],))
        access = cursor.fetchone()['facts']['access']
        recovered = (present(case)['evidence_fresh'] and case['outcome'] == 'healthy'
                     and access['status'] == 'active' and access['revision'] >= receipt['revision'])
    transition(database, operation, 'succeeded' if recovered else 'applied_not_recovered',
               None if recovered else 'current_business_state_not_recovered', receipt, case['latest_observation_id'])


def repair_failed(database, operation, error):
    with database.transaction(operation['workspace_id']) as cursor:
        try:
            row = owned(cursor, operation)
        except ReadFailure:
            return
    state = 'verifying' if row['receipt'] else 'outcome_unknown' if row['dispatch_started_at'] else 'queued'
    if not row['dispatch_started_at'] and (operation['attempts'] >= MAX_ATTEMPTS or not error.retryable):
        state = 'blocked'
    transition(database, operation, state, error.code)


def run_repair(app, workspace):
    operation = claim_repair(app.state.database, workspace)
    if operation is None:
        return False
    if operation['attempts'] > MAX_ATTEMPTS:
        transition(app.state.database, operation, 'outcome_unknown' if operation['dispatch_started_at'] else 'blocked', 'attempt_limit')
        return True
    try:
        execute_repair(app, operation)
    except ReadFailure as error:
        repair_failed(app.state.database, operation, error)
    except httpx.RequestError:
        repair_failed(app.state.database, operation, ReadFailure('target_network_unavailable'))
    return True


@router.post('/api/workspaces/{workspace}/operations/{operation_id}/recover')
def recover(workspace: Identifier, operation_id: Identifier, request: Request):
    subject = actor(request, workspace, write=True)
    with request.app.state.database.transaction(workspace, subject) as cursor:
        cursor.execute('SELECT * FROM repair_operations WHERE operation_id=%s FOR UPDATE', (operation_id,))
        row = cursor.fetchone()
        if row is None:
            raise HTTPException(404, 'Operation not found')
        if row['state'] not in ('outcome_unknown', 'verifying') or row['lease_until'] and row['lease_until'] > datetime.now(UTC):
            raise HTTPException(409, 'Operation is not waiting for recovery')
        cursor.execute('UPDATE repair_operations SET attempts=0,due_at=now() WHERE operation_id=%s', (operation_id,))
        cursor.execute('SELECT case_id,fingerprint FROM repair_proposals WHERE proposal_id=%s', (row['proposal_id'],))
        proposal = cursor.fetchone()
        audit(cursor, workspace, proposal['case_id'], subject, 'recover', 'Retry receipt lookup or business verification with the same identity', proposal['fingerprint'])
    return {'operation_id': operation_id, 'state': row['state']}
