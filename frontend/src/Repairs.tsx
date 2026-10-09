import { useEffect, useState } from 'react';
import { request } from './api';
import type { Detail } from './api';

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
const words = (value: string) => value.replaceAll('_', ' ');

export function Repairs({detail, base, csrf, role, fresh, now, onChanged}: {
  detail: Detail; base: string; csrf: string; role: string | undefined;
  fresh: boolean; now: number; onChanged: () => void;
}) {
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setHistory(null); setConfirmed(false); setReason(''); setError('');
    request<History>(base + `/cases/${detail.case_id}/repairs`, {signal: controller.signal})
      .then(setHistory).catch(e => {if (e.name !== 'AbortError') setError(e.message);});
    return () => controller.abort();
  }, [base, detail.case_id, detail.latest_observation_id]);
  const writable = !!csrf && (role === 'owner' || role === 'operator');
  const active = history?.operations.some(op => ['queued','executing','verifying','outcome_unknown'].includes(op.state));
  const pending = history?.proposals.find(p => p.state === 'pending');
  const valid = pending && Date.parse(pending.expires_at) > now && pending.fingerprint === detail.fingerprint && fresh && detail.current_outcome === 'eligible';
  const canPrepare = writable && fresh && detail.current_outcome === 'eligible' && !active && ['open','awaiting_approval'].includes(detail.state);
  async function action(path: string, body?: object) {
    setBusy(true); setError('');
    try {
      await request(base + path, {method: 'POST', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
      onChanged();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <section className="detail-section" aria-labelledby="repair-title">
    <h3 id="repair-title">Access repair</h3>
    <p>Restore purchased access. Approval queues the change; the worker checks current facts before applying it.</p>
    {error && <p className="alert" role="alert">{error}</p>}
    {!history ? <p className="muted">{error ? 'Repair history could not be loaded.' : 'Loading repair history…'}</p> : <>
      {!valid && !active && <><button className="secondary" disabled={busy || !canPrepare} onClick={() => action(`/cases/${detail.case_id}/proposals`, {
        reason: 'Prepare an access repair for operator review', observation_id: detail.latest_observation_id, fingerprint: detail.fingerprint,
      })}>Prepare repair preview</button><p className="muted action-help">Requires fresh, eligible payment and inactive access evidence.</p></>}
      {pending && <div className="repair-preview"><h4>Repair preview</h4>
        <dl><dt>Action</dt><dd>Grant access</dd><dt>Customer</dt><dd className="mono">{pending.payload.customer_id}</dd>
          <dt>Product</dt><dd>{pending.payload.product_id}</dd><dt>Purchase</dt><dd className="mono">{pending.payload.purchase_id}</dd>
          <dt>Precondition</dt><dd>Never activated, inactive · revision {pending.payload.expected_revision}</dd>
          <dt>Expires</dt><dd>{new Date(pending.expires_at).toLocaleString()}</dd><dt>Prepared by</dt><dd>{pending.created_by}</dd></dl>
        <details><summary>Proposal references</summary><p className="mono">{pending.proposal_id}</p><p className="mono">Payload SHA-256: {pending.payload_digest}</p><p>Policy: {pending.policy_version}</p></details>
        {!valid && <p className="alert">This preview has expired or its evidence changed. Refresh evidence and prepare a new preview.</p>}
        <label htmlFor="repair-reason">Approval or rejection reason</label><textarea id="repair-reason" maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} disabled={!writable || busy}/>
        <label className="confirm-target"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} disabled={!writable || !valid || busy}/>I reviewed the customer, product and exact access change above.</label>
        <div className="decision-actions"><button disabled={busy || !writable || !valid || !confirmed || reason.trim().length < 5} onClick={() => action(`/proposals/${pending.proposal_id}/decisions`, {decision: 'approve', reason, payload_digest: pending.payload_digest})}>Approve and queue repair</button>
          <button className="secondary" disabled={busy || !writable || Date.parse(pending.expires_at) <= now || reason.trim().length < 5} onClick={() => action(`/proposals/${pending.proposal_id}/decisions`, {decision: 'reject', reason, payload_digest: pending.payload_digest})}>Reject proposal</button></div>
      </div>}
      {history.operations.map(op => <div className="record repair-result" key={op.operation_id}><h4>{words(op.state)}</h4><p className="mono">{op.operation_id}</p>
        {op.state === 'outcome_unknown' && <p className="alert">The target may have accepted this repair. Recovery looks up the same operation; another grant is blocked.</p>}
        {['queued','executing','verifying'].includes(op.state) && <p className="muted">Repair is in progress. Refresh evidence to check its result.</p>}
        {op.receipt && <p>Target receipt: {words(op.receipt.result)} · revision {op.receipt.revision}</p>}
        {op.state === 'succeeded' && <p className="notice">Access was verified active by the recorded recovery observation. See the summary for current state.</p>}
        {op.state === 'applied_not_recovered' && <p className="alert">The grant was recorded, but current business evidence does not establish recovery.</p>}
        {op.last_error && <p className="muted">Latest result: {words(op.last_error)}</p>}
        {['outcome_unknown','verifying'].includes(op.state) && op.attempts >= 8 && <button className="secondary" disabled={busy || !writable} onClick={() => action(`/operations/${op.operation_id}/recover`)}>Retry outcome lookup</button>}
      </div>)}
      {!!history.decisions.length && <details><summary>Repair decisions and attempts</summary>{history.decisions.map((decision,i) => <div className="record" key={i}><strong>{words(decision.decision)}</strong><p>{decision.subject} · {new Date(decision.created_at).toLocaleString()}</p><p>{decision.reason}</p></div>)}
        <ol className="timeline">{history.attempts.map((attempt,i) => <li key={i}>{words(attempt.kind)} · {words(attempt.result)}<span>{new Date(attempt.created_at).toLocaleString()}</span></li>)}</ol></details>}
      {!writable && <p className="muted">{role === 'viewer' ? 'Viewers can inspect repair history. An owner or operator must approve changes.' : 'Sign in again to approve changes.'}</p>}
    </>}
  </section>;
}
