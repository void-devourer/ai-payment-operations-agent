"""Translate bounded observations into policy facts and durable case projections.

Called only inside the fenced publication transaction while the purchase head is
locked. No provider/target writes, grants, proposals or approval authority.
"""

from datetime import datetime
import hashlib
import json
import uuid

from psycopg2.extras import Json

from .policy import (AccessBinding,AccessEvidence,AccessStatus,Decision,Environment,
    EvidenceWindow,Outcome,PaymentEvidence,PaymentStatus,ProviderScope,Purchase,
    POLICY_VERSION,evaluate_access)


def material_fingerprint(facts):
    # Read time, generation, pagination and transport errors are not material facts.
    material={key:facts.get(key) for key in ('scope','registered_attempts','payments','refunds','disputes','access')}
    # Simulator revision counters establish read consistency, not new findings.
    material['payments']=[{k:v for k,v in row.items() if k not in ('reversal_generation','latest_charge')}
        for row in facts.get('payments',[])]
    for key in ('payments','refunds','disputes'):
        material[key]=sorted(material.get(key) or [],key=lambda row:json.dumps(row,sort_keys=True))
    return hashlib.sha256(json.dumps({'policy':POLICY_VERSION,'facts':material},sort_keys=True,separators=(',',':')).encode()).hexdigest()


def decision_for(purchase,attempts,facts,clocks,scope,now):
    try:
        binding=AccessBinding(*(purchase[key] for key in ('workspace_id','purchase_id','customer_id','product_id')))
        trusted=ProviderScope(purchase['workspace_id'],purchase['connection_id'],scope['account_id'],Environment(scope['environment']))
        contract=Purchase(binding,trusted,purchase['provider_customer_id'],tuple(attempts),purchase['expected_amount_minor'],purchase['currency'])
        if not facts.get('payments') or not facts.get('access'):
            return evaluate_access(contract,None,None,now=now)
        if facts.get('registered_attempts')!=attempts or sorted(row['payment_intent_id'] for row in facts['payments'])!=attempts:
            return Decision(Outcome.AWAITING_EVIDENCE,('attempt_coverage_mismatch',))
        successful=tuple(sorted(row['payment_intent_id'] for row in facts['payments'] if row['status']=='succeeded'))
        selected=next((row for row in facts['payments'] if row['status']=='succeeded'),facts['payments'][0])
        def window(name):
            value=facts['windows'][name]
            return EvidenceWindow(datetime.fromisoformat(value['started_at']),datetime.fromisoformat(value['finished_at']),
                value['complete'] is True and facts.get(name+'_complete') is True)
        observed_scope=ProviderScope(**(facts['scope']|{'environment':Environment(facts['scope']['environment'])}))
        payment=PaymentEvidence(observed_scope,selected['payment_intent_id'],purchase['provider_customer_id'],
            PaymentStatus(selected['status']),selected['amount_received_minor'],selected['currency'],successful,
            len(facts['refunds']),len(facts['disputes']),window('payment'),window('reversal'),clocks.get(selected['payment_intent_id']))
        value=facts['access']
        access=AccessEvidence(AccessBinding(*(value[key] for key in ('workspace_id','purchase_id','customer_id','product_id'))),
            AccessStatus(value['status']),value['revision'],value['ever_activated'],window('access'))
        return evaluate_access(contract,payment,access,now=now)
    except (KeyError,ValueError,TypeError):
        return Decision(Outcome.AWAITING_EVIDENCE,('invalid_normalized_evidence',))


def apply_observation(cursor,purchase,attempts,observation_id,facts,now):
    workspace,purchase_id=purchase['workspace_id'],purchase['purchase_id']
    cursor.execute('SELECT account_id,environment FROM connections WHERE connection_id=%s',(purchase['connection_id'],))
    scope=dict(cursor.fetchone())
    if facts.get('payment_complete') is True and facts.get('registered_attempts')==attempts:
        for payment in facts['payments']:
            if payment['status']=='succeeded' and payment['payment_intent_id'] in attempts:
                cursor.execute("""INSERT INTO success_clocks VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (workspace,purchase['connection_id'],payment['payment_intent_id'],
                     datetime.fromisoformat(facts['windows']['payment']['finished_at']),observation_id))
    cursor.execute('SELECT payment_intent_id,first_confirmed_at FROM success_clocks WHERE connection_id=%s AND payment_intent_id=ANY(%s)', (purchase['connection_id'],attempts))
    clocks={row['payment_intent_id']:row['first_confirmed_at'] for row in cursor.fetchall()}
    decision=decision_for(purchase,attempts,facts,clocks,scope,now)
    fingerprint=material_fingerprint(facts)
    cursor.execute('INSERT INTO evaluations VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        (workspace,observation_id,purchase_id,decision.policy_version,decision.outcome,Json(list(decision.reasons)),fingerprint,now))
    active_states=('open','awaiting_evidence','awaiting_approval','repair_in_progress','outcome_unknown')
    cursor.execute("SELECT * FROM cases WHERE purchase_id=%s AND state=ANY(%s) FOR UPDATE",(purchase_id,list(active_states)))
    for case in cursor.fetchall():
        state='awaiting_evidence' if decision.outcome is Outcome.AWAITING_EVIDENCE else 'open'
        if case['state'] in ('repair_in_progress','outcome_unknown'):
            state=case['state']
        elif case['state']=='awaiting_approval' and case['fingerprint']==fingerprint and decision.outcome is Outcome.ELIGIBLE:
            state='awaiting_approval'
        if case['discrepancy_code']=='PAID_ACCESS_MISSING' and decision.outcome is Outcome.HEALTHY and case['state']!='outcome_unknown':
            state='resolved'
            cursor.execute("INSERT INTO case_audit(workspace_id,audit_id,case_id,subject,action,reason,fingerprint) VALUES (%s,%s,%s,'system','resolve','Current authoritative access is active',%s)",
                (workspace,uuid.uuid4().hex,case['case_id'],fingerprint))
        cursor.execute('UPDATE cases SET state=%s,latest_observation_id=%s,fingerprint=%s,updated_at=%s WHERE case_id=%s',
            (state,observation_id,fingerprint,now,case['case_id']))
    code=None
    if decision.outcome is Outcome.ELIGIBLE:
        code='PAID_ACCESS_MISSING'
    elif decision.outcome is Outcome.MANUAL_REVIEW:
        code='REVERSAL_ACCESS_REVIEW' if set(decision.reasons)&{'refund_history','dispute_history'} else 'PAYMENT_REVIEW'
    if code is None:
        return
    cursor.execute('SELECT state,fingerprint,generation FROM cases WHERE purchase_id=%s AND discrepancy_code=%s ORDER BY generation DESC LIMIT 1', (purchase_id,code))
    previous=cursor.fetchone()
    if previous and (previous['state'] in active_states or
                     previous['state']=='dismissed' and previous['fingerprint']==fingerprint):
        return
    cursor.execute('INSERT INTO cases VALUES (%s,%s,%s,%s,%s,\'open\',%s,%s,%s,%s,%s)',
        (workspace,uuid.uuid4().hex,purchase_id,code,previous['generation']+1 if previous else 1,
         fingerprint,observation_id,observation_id,now,now))
