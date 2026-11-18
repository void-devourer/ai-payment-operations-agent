"""Workspace-scoped case investigation and payload-bound operator dismissal."""

from datetime import UTC,datetime,timedelta
import uuid
import math

from fastapi import APIRouter,HTTPException,Query,Request
from pydantic import BaseModel,ConfigDict,Field

from .contracts import Identifier
from .security import actor
from .jobs import enqueue,enqueue_purchase

router=APIRouter()


def check_availability(cursor, case_id):
    cursor.execute("""SELECT now() AS server_now,
        max(created_at + interval '30 seconds') FILTER (WHERE case_id=%s) AS case_until,
        CASE WHEN count(*)>=6 THEN min(created_at) + interval '1 minute' END AS workspace_until
        FROM case_audit WHERE action='request_check' AND created_at>now()-interval '1 minute'""", (case_id,))
    row=cursor.fetchone()
    until=max(t for t in (row['server_now'],row['case_until'],row['workspace_until']) if t is not None)
    seconds=max(0,math.ceil((until-row['server_now']).total_seconds()))
    return {'retry_after_seconds':seconds,'allowed':seconds==0}


@router.get('/api/workspaces/{workspace}/cases/{case_id}/check-availability')
def available_check(workspace: Identifier,case_id: Identifier,request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute('SELECT 1 FROM cases WHERE case_id=%s',(case_id,))
        if cursor.fetchone() is None:
            raise HTTPException(404,'Case not found')
        return check_availability(cursor,case_id)


@router.post('/api/workspaces/{workspace}/cases/{case_id}/check',status_code=202)
def request_check(workspace: Identifier,case_id: Identifier,request: Request):
    subject=actor(request,workspace,write=True)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        # Serialize operator requests within this workspace, including cooldown
        # checks. Worker publication does not acquire this advisory lock.
        cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('operator_check:'+workspace,))
        cursor.execute('SELECT purchase_id,fingerprint FROM cases WHERE case_id=%s',(case_id,))
        case=cursor.fetchone()
        if case is None:
            raise HTTPException(404,'Case not found')
        limit=check_availability(cursor,case_id)
        if not limit['allowed']:
            raise HTTPException(429,'A check was recently requested; wait before requesting another',
                                headers={'Retry-After':str(limit['retry_after_seconds'])})
        # One read gathers all registered attempts for the purchase. Do not
        # multiply the workload by enqueueing each attempt separately.
        cursor.execute('SELECT connection_id FROM purchases WHERE purchase_id=%s',(case['purchase_id'],))
        connection=cursor.fetchone()['connection_id']
        if connection.startswith('paypal_'):
            job_id=enqueue_purchase(cursor,workspace,connection,case['purchase_id'])
        else:
            cursor.execute('SELECT connection_id,payment_intent_id FROM payment_attempts WHERE purchase_id=%s ORDER BY payment_intent_id LIMIT 1',(case['purchase_id'],))
            attempt=cursor.fetchone()
            if attempt is None:
                raise HTTPException(409,'No registered payment attempt available')
            job_id=enqueue(cursor,workspace,attempt['connection_id'],attempt['payment_intent_id'])
        cursor.execute("INSERT INTO case_audit(workspace_id,audit_id,case_id,subject,action,reason,fingerprint) VALUES (%s,%s,%s,%s,'request_check','Requested current source records',%s)",
                       (workspace,uuid.uuid4().hex,case_id,subject,case['fingerprint']))
        cursor.execute('SELECT now() AS requested_at')
        return {'job_id':job_id,'requested_at':cursor.fetchone()['requested_at'],**check_availability(cursor,case_id)}


@router.get('/api/workspaces/{workspace}/cases/{case_id}/checks/{job_id}')
def check_status(workspace: Identifier,case_id: Identifier,job_id: Identifier,request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT j.state,j.due_at,j.last_error,o.started_at,o.finished_at,o.observation_id
            FROM cases c JOIN purchases p USING(workspace_id,purchase_id)
            JOIN jobs j ON j.workspace_id=p.workspace_id AND j.connection_id=p.connection_id AND
                (j.purchase_id=p.purchase_id OR EXISTS(SELECT 1 FROM payment_attempts a WHERE
                    a.workspace_id=p.workspace_id AND a.purchase_id=p.purchase_id AND a.payment_intent_id=j.payment_intent_id AND a.connection_id=j.connection_id))
            LEFT JOIN evidence_heads h ON h.workspace_id=c.workspace_id AND h.purchase_id=c.purchase_id
            LEFT JOIN observations o ON o.workspace_id=h.workspace_id AND o.observation_id=h.observation_id AND o.generation=h.generation
            WHERE c.case_id=%s AND j.job_id=%s""",(case_id,job_id))
        row=cursor.fetchone()
        if row is None:
            raise HTTPException(404,'Check not found for this case')
        return dict(row)


class Dismissal(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    reason: str=Field(min_length=5,max_length=1000)
    observation_id: Identifier
    fingerprint: str=Field(pattern=r'^[a-f0-9]{64}$')


def present(row):
    value=dict(row)
    windows=value.pop('windows',None) or {}
    if value.get('provider')=='paypal': windows={key:window for key,window in windows.items() if key in ('payment','access')}
    now=datetime.now(UTC)
    fresh=len(windows)==(2 if value.get('provider')=='paypal' else 3) and all(window.get('complete') is True and
        datetime.fromisoformat(window['finished_at'])<=now and
        timedelta(0)<=now-datetime.fromisoformat(window['started_at'])<=timedelta(seconds=60)
        for window in windows.values())
    value['evidence_fresh']=fresh and value.pop('is_current',False)
    value['fresh_until']=(min(datetime.fromisoformat(window['started_at']) for window in windows.values())
        +timedelta(seconds=60)).isoformat() if value['evidence_fresh'] else None
    value['current_outcome']=value.get('outcome') if value['evidence_fresh'] else 'awaiting_evidence'
    if not value['evidence_fresh']:
        value['current_reasons']=['stale_or_incomplete_observation']
    else:
        value['current_reasons']=value.get('reasons',[])
    return value


CASE_SELECT="""SELECT c.*,e.outcome,e.reasons,e.policy_version,e.evaluated_at,cn.provider,
    o.facts->'windows' AS windows,(h.observation_id=c.latest_observation_id AND h.generation=o.generation) AS is_current
    FROM cases c JOIN evaluations e ON e.workspace_id=c.workspace_id AND e.observation_id=c.latest_observation_id
    JOIN observations o ON o.workspace_id=c.workspace_id AND o.observation_id=c.latest_observation_id
    JOIN evidence_heads h ON h.workspace_id=c.workspace_id AND h.purchase_id=c.purchase_id
    JOIN purchases p ON p.workspace_id=c.workspace_id AND p.purchase_id=c.purchase_id
    JOIN connections cn ON cn.workspace_id=p.workspace_id AND cn.connection_id=p.connection_id"""


@router.get('/api/workspaces/{workspace}/cases')
def list_cases(workspace: Identifier,request: Request,after: Identifier|None=None):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute(CASE_SELECT+' WHERE c.case_id>%s ORDER BY c.case_id LIMIT 51',(after or '',))
        rows=cursor.fetchall()
        return {'data':[present(row) for row in rows[:50]],'next_cursor':rows[49]['case_id'] if len(rows)>50 else None}


@router.get('/api/workspaces/{workspace}/cases/{case_id}')
def case_detail(workspace: Identifier,case_id: Identifier,request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute(CASE_SELECT+' WHERE c.case_id=%s',(case_id,))
        row=cursor.fetchone()
        if row is None:
            raise HTTPException(404,'Case not found')
        result=present(row)
        cursor.execute('SELECT payload FROM purchases WHERE purchase_id=%s',(row['purchase_id'],))
        result['purchase']=cursor.fetchone()['payload']
        cursor.execute('SELECT facts,content_digest,source,api_version,normalizer_version,started_at,finished_at FROM observations WHERE observation_id=%s',(row['latest_observation_id'],))
        result['observation']=dict(cursor.fetchone())
        cursor.execute('SELECT subject,action,reason,created_at FROM case_audit WHERE case_id=%s ORDER BY created_at DESC LIMIT 50',(case_id,))
        result['audit']=cursor.fetchall()
        return result


@router.get('/api/workspaces/{workspace}/purchases/{purchase_id}/timeline')
def timeline(workspace: Identifier,purchase_id: Identifier,request: Request,
             before_generation: int|None=Query(default=None,ge=1)):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute('SELECT 1 FROM purchases WHERE purchase_id=%s',(purchase_id,))
        if cursor.fetchone() is None:
            raise HTTPException(404,'Purchase not found')
        cursor.execute("""SELECT o.observation_id,o.generation,o.started_at,o.finished_at,o.source,o.api_version,
            o.content_digest,coalesce(e.outcome,'awaiting_evidence') AS outcome,
            coalesce(e.reasons,'["policy_not_evaluated"]'::jsonb) AS reasons,e.policy_version,o.facts FROM observations o
            LEFT JOIN evaluations e USING(workspace_id,observation_id) WHERE o.purchase_id=%s
            AND (%s IS NULL OR o.generation<%s) ORDER BY o.generation DESC LIMIT 51""",
            (purchase_id,before_generation,before_generation))
        rows=cursor.fetchall()
        return {'data':rows[:50],'next_generation':rows[49]['generation'] if len(rows)>50 else None}


@router.post('/api/workspaces/{workspace}/cases/{case_id}/dismiss')
def dismiss(workspace: Identifier,case_id: Identifier,body: Dismissal,request: Request):
    subject=actor(request,workspace,write=True,recent=True)
    if len(body.reason.strip())<5:
        raise HTTPException(422,'A meaningful disposition reason is required')
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute('SELECT purchase_id FROM cases WHERE case_id=%s',(case_id,))
        row=cursor.fetchone()
        if row is None:
            raise HTTPException(404,'Case not found')
        # Publication locks head -> case; use the same order to avoid a deadlock.
        cursor.execute('SELECT observation_id,generation FROM evidence_heads WHERE purchase_id=%s FOR UPDATE',(row['purchase_id'],))
        head=cursor.fetchone()
        cursor.execute(CASE_SELECT+' WHERE c.case_id=%s FOR UPDATE OF c',(case_id,))
        case=cursor.fetchone()
        if (case['state'] not in ('open','awaiting_evidence','awaiting_approval') or
            case['latest_observation_id']!=body.observation_id or case['fingerprint']!=body.fingerprint or
            head['observation_id']!=body.observation_id or not present(case)['evidence_fresh']):
            raise HTTPException(409,'Case/evidence changed or is incomplete; refresh before dismissing')
        cursor.execute("UPDATE cases SET state='dismissed',updated_at=now() WHERE case_id=%s",(case_id,))
        cursor.execute("UPDATE repair_proposals SET state='superseded' WHERE case_id=%s AND state='pending'",(case_id,))
        cursor.execute('INSERT INTO case_audit(workspace_id,audit_id,case_id,subject,action,reason,fingerprint) VALUES (%s,%s,%s,%s,\'dismiss\',%s,%s)',
            (workspace,uuid.uuid4().hex,case_id,subject,body.reason.strip(),body.fingerprint))
    return {'case_id':case_id,'state':'dismissed'}


@router.get('/api/workspaces/{workspace}/reconciliation')
def coverage(workspace: Identifier,request: Request):
    subject=actor(request,workspace)
    with request.app.state.database.transaction(workspace,subject) as cursor:
        cursor.execute("""SELECT DISTINCT ON (connection_id) run_id,connection_id,state,cutoff_at,
            after_purchase_id,scheduled_purchases,unbound_purchases,started_at,finished_at
            FROM reconciliation_runs ORDER BY connection_id,started_at DESC""")
        runs=cursor.fetchall()
        cursor.execute("""SELECT count(*) AS registered_purchases,
            count(*) FILTER(WHERE o.observation_id IS NULL OR h.generation<>o.generation) AS unobserved,
            count(*) FILTER(WHERE o.observation_id IS NOT NULL AND
                (o.facts->>'payment_complete'<>'true' OR o.facts->>'reversal_complete'<>'true'
                 OR o.facts->>'access_complete'<>'true')) AS incomplete,
            count(*) FILTER(WHERE o.started_at<now()-interval '60 seconds') AS stale
            FROM purchases p LEFT JOIN evidence_heads h USING(workspace_id,purchase_id)
            LEFT JOIN observations o ON o.workspace_id=h.workspace_id AND o.observation_id=h.observation_id""")
        return {'scope':'registered_purchases_all_ages','scan_state_means':'read_jobs_scheduled_not_reads_verified',
            'provider_inventory_backfill':'unsupported','event_history_reconstruction':'unsupported',
            'runs':runs,'evidence_coverage':dict(cursor.fetchone())}
