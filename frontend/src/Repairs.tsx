import { useCallback, useEffect, useState } from 'react';
import { ApiError, request } from './api';
import type { Detail } from './api';
import { Notice } from './Notice';

type Proposal = {
  proposal_id: string; state: string; expires_at: string; fingerprint: string;
  payload_digest: string; policy_version: string; created_by: string;
  payload: { customer_id: string; product_id: string; purchase_id: string; expected_revision: number };
};
type Operation = { operation_id: string; state: string; last_error: string | null; attempts: number;
  receipt: { result: string; revision: number } | null };
type History = { proposals: Proposal[]; operations: Operation[];
  decisions: { subject: string; decision: string; reason: string; created_at: string }[];
  attempts: {kind: string; result: string; created_at: string}[] };
import { label as words, reference } from './labels';

export function Repairs({detail, base, csrf, role, fresh, now, confirmedIdentity, onConfirm, onChanged}: {
  detail: Detail; base: string; csrf: string; role: string | undefined;
  fresh: boolean; now: number; confirmedIdentity: boolean; onConfirm: () => void; onChanged: () => void;
}) {
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState('');
  const closeError = useCallback(() => setError(''), []);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setConfirmed(false); setReason(''); setError('');
    request<History>(base + `/cases/${detail.case_id}/repairs`, {signal: controller.signal})
      .then(rows => {if (!controller.signal.aborted) setHistory(rows);}).catch(e => {if (e.name !== 'AbortError') setError(e.message);});
    return () => controller.abort();
  }, [base, detail.case_id, detail.latest_observation_id, detail.updated_at]);
  const writable = confirmedIdentity && !!csrf && (role === 'owner' || role === 'operator');
  const active = history?.operations.some(op => ['queued','executing','verifying','outcome_unknown'].includes(op.state));
  const pending = history?.proposals.find(p => p.state === 'pending');
  const valid = pending && Date.parse(pending.expires_at) > now && pending.fingerprint === detail.fingerprint && fresh && detail.current_outcome === 'eligible';
  const canPrepare = writable && fresh && detail.current_outcome === 'eligible' && !active && ['open','awaiting_approval'].includes(detail.state);
  async function action(path: string, body?: object) {
    setBusy(true); setError('');
    try {
      await request(base + path, {method: 'POST', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
      onChanged();
    } catch (e) {if (e instanceof ApiError && e.status === 428) onConfirm(); else setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="detail-section" aria-labelledby="repair-title">
    <h3 id="repair-title">Restore customer access</h3>
    <p>Review the access change, then approve it for the customer.</p>
    <Notice text={error} onClose={closeError} error/>
    {!history ? <p className="muted">{error ? 'Repair history could not be loaded.' : 'Loading repair history…'}</p> : <>
      {!valid && !active && <><button className="secondary" disabled={busy || !canPrepare} onClick={() => action(`/cases/${detail.case_id}/proposals`, {
        reason: 'Prepare an access repair for operator review', observation_id: detail.latest_observation_id, fingerprint: detail.fingerprint,
      })}>Review access change</button><p className="muted action-help">{!fresh ? 'Check latest records first.' : detail.current_outcome !== 'eligible' ? 'This finding needs review before access can be restored.' : !confirmedIdentity ? 'Confirm your identity to make changes.' : 'Review the customer and product before approving.'}</p></>}
      {pending && valid && <div className="repair-preview"><h4>Proposed access change</h4>
        <dl><dt>Action</dt><dd>Grant access</dd><dt>Customer</dt><dd>Customer {reference(pending.payload.customer_id)}</dd>
          <dt>Product</dt><dd>{words(pending.payload.product_id)}</dd><dt>Purchase</dt><dd>Purchase {reference(pending.payload.purchase_id)}</dd>
          <dt>Precondition</dt><dd>Customer access has never been activated</dd>
          <dt>Expires</dt><dd>{new Date(pending.expires_at).toLocaleString()}</dd><dt>Prepared by</dt><dd>{words(pending.created_by)}</dd></dl>
        <details><summary>Full customer and proposal references</summary><p className="mono">Customer: {pending.payload.customer_id}</p><p className="mono">Purchase: {pending.payload.purchase_id}</p><p className="mono">{pending.proposal_id}</p><p className="mono">Payload SHA-256: {pending.payload_digest}</p><p>Policy: {pending.policy_version}</p><p>Expected access record version: {pending.payload.expected_revision}</p></details>
        <label htmlFor="repair-reason">Approval or rejection reason</label><textarea id="repair-reason" maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} disabled={!writable || busy}/>
        <label className="confirm-target"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={!writable || !valid || busy}/>I reviewed the customer, product and exact access change above.</label>
        <div className="decision-actions"><button disabled={busy || !writable || !valid || !confirmed || reason.trim().length < 5} onClick={() => action(`/proposals/${pending.proposal_id}/decisions`, {decision: 'approve', reason, payload_digest: pending.payload_digest})}>Approve and queue repair</button>
          <button className="secondary" disabled={busy || !writable || Date.parse(pending.expires_at) <= now || reason.trim().length < 5} onClick={() => action(`/proposals/${pending.proposal_id}/decisions`, {decision: 'reject', reason, payload_digest: pending.payload_digest})}>Reject proposal</button></div>
      </div>}
      {pending && !valid && <details><summary>Previous access preview</summary><p>This preview is out of date. Check latest records and review the access change again.</p><p className="mono">{pending.proposal_id}</p><p>Prepared by {words(pending.created_by)} · expires {new Date(pending.expires_at).toLocaleString()}</p></details>}
      {history.operations.map(op => <div className="record repair-result" key={op.operation_id}><h4>{words(op.state)}</h4><details className="reference-details"><summary>Operation reference</summary><p className="mono">{op.operation_id}</p></details>
        {op.state === 'outcome_unknown' && <p className="alert">The target may have accepted this repair. Recovery looks up the same operation; another grant is blocked.</p>}
        {['queued','executing','verifying'].includes(op.state) && <p className="muted">The access change is processing. Its result will appear automatically.</p>}
        {op.receipt && <p>Application result: {words(op.receipt.result)}</p>}
        {op.state === 'succeeded' && <p className="notice">Customer access was restored and verified. The summary shows the latest recorded state.</p>}
        {op.state === 'applied_not_recovered' && <p className="alert">The grant was recorded, but current business evidence does not establish recovery.</p>}
        {op.last_error && <p className="muted">Latest result: {words(op.last_error)}</p>}
        {['outcome_unknown','verifying'].includes(op.state) && op.attempts >= 8 && <button className="secondary" disabled={busy || !writable} onClick={() => action(`/operations/${op.operation_id}/recover`)}>Retry outcome lookup</button>}
      </div>)}
      {!!history.decisions.length && <details><summary>Repair decisions and attempts</summary>{history.decisions.map((decision,i) => <div className="record" key={i}><strong>{words(decision.decision)}</strong><p>{decision.subject} · {new Date(decision.created_at).toLocaleString()}</p><p>{decision.reason}</p></div>)}
        <ol className="timeline">{history.attempts.map((attempt,i) => <li key={i}>{words(attempt.kind)} · {words(attempt.result)}<span>{new Date(attempt.created_at).toLocaleString()}</span></li>)}</ol></details>}
      {role === 'viewer' ? <p className="muted">An owner or operator can approve access changes.</p> : !confirmedIdentity && <button className="secondary" onClick={onConfirm}>Confirm identity to make changes</button>}
    </>}
  </section>;
}
