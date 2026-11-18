"""Typed, bounded PayPal evidence. Investigation never authorizes an access grant."""
from dataclasses import asdict
from datetime import UTC,datetime,timedelta
from decimal import Decimal
import hashlib
import json
import re
import time
import uuid

from psycopg2.extras import Json

from .jobs import ReadFailure,finish,heartbeat,lock_owned,reserve_request
from .paypal_provider import PayPalSandboxClient,VERSION,resource_id
from .detection.policy import Decision,Outcome

POLICY='paypal_investigation_v1'
CAPABILITIES={'order_read':True,'capture_read':True,'buyer_binding':True,
    'refund_inventory':False,'dispute_inventory':False,'bank_settlement':False,'access_repair':False}


def require(condition):
    if not condition: raise ReadFailure('paypal_order_scope_or_shape',False)


def amount(value):
    require(isinstance(value,dict) and value.get('currency_code')=='USD')
    text=value.get('value')
    require(isinstance(text,str) and re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?',text) is not None)
    minor=int(Decimal(text)*100)
    require(0<minor<=10**12)
    return minor


def normalize_order(body,order_id,purchase,merchant):
    require(isinstance(body,dict) and body.get('id')==order_id and body.get('intent')=='CAPTURE')
    require(body.get('status') in ('CREATED','SAVED','APPROVED','VOIDED','COMPLETED','PAYER_ACTION_REQUIRED'))
    units=body.get('purchase_units')
    require(isinstance(units,list) and len(units)==1 and isinstance(units[0],dict))
    unit=units[0]
    require(isinstance(unit.get('payee'),dict) and unit['payee'].get('merchant_id')==merchant)
    payer=body.get('payer',{})
    source=body.get('payment_source',{})
    require(isinstance(payer,dict) and isinstance(source,dict) and isinstance(source.get('paypal',{}),dict))
    buyers=[value for value in (payer.get('payer_id'),source.get('paypal',{}).get('account_id')) if value is not None]
    if not buyers: raise ReadFailure('paypal_buyer_unconfirmed')
    require(all(value==purchase['provider_customer_id'] for value in buyers))
    # Trusted server registration establishes the purchase relation. Optional
    # custom_id is only a consistency check, never registration authority.
    require(unit.get('custom_id',purchase['purchase_id'])==purchase['purchase_id'])
    payments=unit.get('payments',{})
    require(isinstance(payments,dict) and not payments.get('authorizations'))
    captures=payments.get('captures',[])
    require(isinstance(captures,list) and len(captures)<=20)
    rows=[]
    for capture in captures:
        require(isinstance(capture,dict))
        key=resource_id(capture.get('id'))
        require(capture.get('status') in ('COMPLETED','DECLINED','PARTIALLY_REFUNDED','PENDING','REFUNDED','FAILED'))
        rows.append({'capture_id':key,'status':capture['status'],'amount_minor':amount(capture.get('amount')),'currency':'usd'})
    require(len({row['capture_id'] for row in rows})==len(rows))
    return {'order_id':order_id,'status':body['status'],'buyer_id':purchase['provider_customer_id'],
        'merchant_id':merchant,'amount_minor':amount(unit.get('amount')),'currency':'usd',
        'captures':sorted(rows,key=lambda row:row['capture_id'])}


def bindings(cursor,purchase_id):
    cursor.execute('SELECT order_id FROM paypal_orders WHERE purchase_id=%s ORDER BY order_id',(purchase_id,))
    orders=[row['order_id'] for row in cursor.fetchall()]
    cursor.execute('''SELECT c.order_id,c.capture_id FROM paypal_captures c JOIN paypal_orders o
        USING(workspace_id,connection_id,order_id) WHERE o.purchase_id=%s ORDER BY c.order_id,c.capture_id''',(purchase_id,))
    return {'orders':orders,'captures':[dict(row) for row in cursor.fetchall()]}


def decision_for(purchase,facts,scope,now):
    # Separate investigation policy: even forged complete flags cannot enter the
    # one_time_access_v1 repair predicate or make PayPal actions eligible.
    expected={'workspace_id':purchase['workspace_id'],'connection_id':purchase['connection_id'],
        'account_id':scope['account_id'],'environment':'test'}
    if facts.get('scope')!=expected:
        return Decision(Outcome.AWAITING_EVIDENCE,('provider_scope_mismatch',),POLICY)
    for name in ('payment','access'):
        window=facts.get('windows',{}).get(name,{})
        try:
            start=datetime.fromisoformat(window['started_at']); end=datetime.fromisoformat(window['finished_at'])
            current=start<=end<=now and now-start<=timedelta(seconds=60)
        except (KeyError,TypeError,ValueError): current=False
        if facts.get(name+'_complete') is not True or window.get('complete') is not True or not current:
            return Decision(Outcome.AWAITING_EVIDENCE,(name+'_incomplete',),POLICY)
    reasons=[]
    payments=facts.get('payments',[])
    paid=[row for row in payments if row.get('status')=='COMPLETED']
    if len(paid)>1: reasons.append('multiple_captures_need_review')
    if any(row.get('status') in ('REFUNDED','PARTIALLY_REFUNDED') for row in payments): reasons.append('capture_reversal_reported')
    if not paid: reasons.append('payment_capture_not_confirmed')
    if any(row.get('amount_minor')!=purchase['expected_amount_minor'] or row.get('currency')!=purchase['currency'] for row in paid):
        reasons.append('payment_value_mismatch')
    access=facts.get('access') or {}
    if paid and access.get('status')=='inactive': reasons.append('paid_access_missing')
    elif access.get('status')=='active': reasons.append('access_already_active')
    elif access.get('status') in ('suspended','revoked'): reasons.append('intentional_access_block')
    reasons.extend(('paypal_reversal_coverage_unknown','paypal_repair_unsupported'))
    return Decision(Outcome.MANUAL_REVIEW,tuple(reasons),POLICY)


def collect(app,job):
    from .evidence import Reader,require as require_access
    database,settings=app.state.database,app.state.settings
    workspace,purchase_id=job['workspace_id'],job['purchase_id']
    connection=settings.paypal.get(workspace)
    if connection is None or job['connection_id']!=f'paypal_{workspace}':
        raise ReadFailure('paypal_connection_unconfigured',False)
    with database.transaction(workspace) as cursor:
        lock_owned(cursor,job)
        cursor.execute('SELECT * FROM purchases WHERE purchase_id=%s AND connection_id=%s',(purchase_id,job['connection_id']))
        row=cursor.fetchone()
        if row is None: raise ReadFailure('binding_not_registered',False)
        purchase=dict(row); registered=bindings(cursor,purchase_id)
        cursor.execute('''INSERT INTO evidence_heads(workspace_id,purchase_id,generation) VALUES (%s,%s,1)
            ON CONFLICT(workspace_id,purchase_id) DO UPDATE SET generation=evidence_heads.generation+1 RETURNING generation''',
            (workspace,purchase_id))
        generation=cursor.fetchone()['generation']
    reader=Reader(app,job)
    # The worker owns this cache; its workspace loop owns the HTTP client.
    clients=getattr(app.state,'paypal_readers',None)
    if clients is None: clients={}; app.state.paypal_readers=clients
    client=clients.setdefault(workspace,PayPalSandboxClient(connection,app.state.http))
    def budget():
        if reader.count>=30 or time.monotonic()-reader.start>=20: raise ReadFailure('read_budget')
        heartbeat(database,job)
        while not reserve_request(database,workspace,job['connection_id']):
            if time.monotonic()-reader.start>=20: raise ReadFailure('connection_budget',delay=1)
            time.sleep(.05)
        reader.count+=1
    client.before_request=budget
    started=datetime.now(UTC)
    facts={'provider':'paypal','api_version':VERSION,'scope':{'workspace_id':workspace,'connection_id':job['connection_id'],
        'account_id':connection.merchant_id,'environment':'test'},'registered_resources':registered,
        'registered_attempts':[],'orders':[],'payments':[],'refunds':[],'disputes':[],'access':None,
        'payment_complete':False,'reversal_complete':False,'access_complete':False,'financial_complete':False,
        'capabilities':CAPABILITIES.copy(),'errors':[],'windows':{},
        'coverage':{'payments':'registered_orders_and_captures','refunds':'unknown','disputes':'unknown','settlement':'unknown'}}
    errors=[]
    for bundle in ('payment','access'):
        window_start=datetime.now(UTC)
        try:
            if bundle=='payment':
                if not registered['orders'] or len(registered['orders'])>5 or len(registered['orders'])+len(registered['captures'])>20:
                    raise ReadFailure('paypal_binding_budget',False)
                for order_id in registered['orders']:
                    order=client.order(order_id,purchase)
                    expected=[row['capture_id'] for row in registered['captures'] if row['order_id']==order_id]
                    if [row['capture_id'] for row in order['captures']]!=sorted(expected):
                        raise ReadFailure('paypal_capture_coverage_changed')
                    rows=[]
                    for capture_id in expected:
                        fact=asdict(client.capture(capture_id,order_id))
                        fact['created_at']=fact['created_at'].isoformat(); fact['updated_at']=fact['updated_at'].isoformat()
                        embedded=next(row for row in order['captures'] if row['capture_id']==capture_id)
                        if any(fact[key]!=embedded[key] for key in ('status','amount_minor','currency')):
                            raise ReadFailure('paypal_order_changed')
                        rows.append(fact)
                    if client.order(order_id,purchase)!=order: raise ReadFailure('paypal_order_changed')
                    facts['orders'].append(order); facts['payments'].extend(rows)
            else:
                access=reader.get(settings.reference_url,f'/internal/access/{purchase_id}','adapter')
                require_access(all(access.get(key)==purchase[key] for key in ('workspace_id','purchase_id','customer_id','product_id'))
                    and access.get('complete') is True and access.get('status') in ('inactive','active','suspended','revoked')
                    and type(access.get('revision')) is int and access['revision']>=0 and type(access.get('ever_activated')) is bool)
                facts['access']={key:access[key] for key in ('workspace_id','purchase_id','customer_id','product_id','status','revision','ever_activated')}
            if time.monotonic()-reader.start>=20: raise ReadFailure('read_budget')
            facts[bundle+'_complete']=True
        except ValueError:
            error=ReadFailure('paypal_order_scope_or_shape',False); errors.append(error)
            facts['errors'].append({'bundle':bundle,'code':error.code})
        except ReadFailure as error:
            errors.append(error); facts['errors'].append({'bundle':bundle,'code':error.code})
            if error.code=='paypal_rate_limited':
                with database.transaction(workspace) as cursor:
                    cursor.execute("UPDATE connections SET next_request_at=greatest(next_request_at,clock_timestamp()+%s*interval '1 second') WHERE connection_id=%s",
                                   (error.delay,job['connection_id']))
        facts['windows'][bundle]={'started_at':window_start.isoformat(),'finished_at':datetime.now(UTC).isoformat(),
                                  'complete':facts[bundle+'_complete']}
    facts['windows']['reversal']={'started_at':started.isoformat(),'finished_at':datetime.now(UTC).isoformat(),'complete':False}
    error=next((value for value in errors if not value.retryable),errors[0] if errors else None)
    finished=datetime.now(UTC); observation=uuid.uuid4().hex
    canonical=json.dumps(facts,sort_keys=True,separators=(',',':'))
    with database.transaction(workspace) as cursor:
        lock_owned(cursor,job)
        cursor.execute('SELECT generation FROM evidence_heads WHERE purchase_id=%s FOR UPDATE',(purchase_id,))
        if cursor.fetchone()['generation']!=generation or bindings(cursor,purchase_id)!=registered:
            raise ReadFailure('observation_superseded')
        lock_owned(cursor,job)
        cursor.execute('INSERT INTO observations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (workspace,observation,purchase_id,job['job_id'],generation,Json(facts),hashlib.sha256(canonical.encode()).hexdigest(),
             started,finished,'paypal_api_and_target',VERSION,POLICY))
        cursor.execute('UPDATE evidence_heads SET observation_id=%s WHERE purchase_id=%s',(observation,purchase_id))
        from .detection.projection import apply_observation
        apply_observation(cursor,purchase,[],observation,facts,finished)
        if error is None: finish(cursor,job)
    if error: raise error
