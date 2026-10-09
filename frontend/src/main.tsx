import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { FormEvent } from 'react';
import { request } from './api';
import type { Case, Coverage, Detail, Health, Timeline, Workspace } from './api';
import './style.css';

const words = (value: string) => value.replaceAll('_', ' ').toLowerCase();
const when = (value: string | null) => value ? new Date(value).toLocaleString() : 'In progress';
const money = (amount: number, currency: string) => currency === 'usd'
  ? new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(amount / 100)
  : `${amount} minor units (${currency.toUpperCase()})`;

function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState('');
  const [csrf, setCsrf] = useState('');
  const [subject, setSubject] = useState('owner_a');
  const [loginKey, setLoginKey] = useState('');
  const [cases, setCases] = useState<Case[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [timeline, setTimeline] = useState<Timeline[]>([]);
  const [timelineCursor, setTimelineCursor] = useState<number | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [now, setNow] = useState(Date.now());
  const title = useRef<HTMLHeadingElement>(null);
  const role = workspaces.find(w => w.workspace_id === workspace)?.role;
  const base = `/api/workspaces/${encodeURIComponent(workspace)}`;
  const isFresh = (c: Case) => c.evidence_fresh && !!c.fresh_until && Date.parse(c.fresh_until) > now;

  function openWorkspace(value: string) {
    setCases([]); setCursor(null); setCoverage(null); setHealth(null);
    setSelected(''); setDetail(null); setTimeline([]); setTimelineCursor(null);
    setWorkspace(value); setMessage('');
  }

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    request<Workspace[]>('/api/workspaces', {signal: controller.signal}).then(rows => {
      setWorkspaces(rows); openWorkspace(rows[0]?.workspace_id ?? '');
    }).catch(e => { if (e.name !== 'AbortError' && !String(e.message).includes('Session expired')) setError(e.message); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!workspace) return;
    const controller = new AbortController();
    setBusy(true);
    Promise.all([
      request<{data: Case[]; next_cursor: string | null}>(base + '/cases', {signal: controller.signal}),
      request<Coverage>(base + '/reconciliation', {signal: controller.signal}),
      request<Health>(base + '/integration-health', {signal: controller.signal}),
    ]).then(([rows, scan, integrations]) => {
      setCases(rows.data); setCursor(rows.next_cursor); setCoverage(scan); setHealth(integrations); setError('');
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [workspace, refresh]);

  useEffect(() => {
    if (!workspace || !selected) { setDetail(null); setTimeline([]); return; }
    const controller = new AbortController();
    setDetail(null); setTimeline([]); setReason('');
    request<Detail>(base + `/cases/${selected}`, {signal: controller.signal}).then(async d => {
      const history = await request<{data: Timeline[]; next_generation: number | null}>(base + `/purchases/${d.purchase_id}/timeline`, {signal: controller.signal});
      return [d, history] as const;
    }).then(([d, history]) => {
      setDetail(d); setTimeline(history.data); setTimelineCursor(history.next_generation);
      title.current?.focus();
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [workspace, selected, refresh]);

  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const session = await request<{csrf_token: string}>(`/dev/sessions/${subject}`, {method: 'POST', headers: {'X-Demo-Login-Key': loginKey}});
      setCsrf(session.csrf_token); setLoginKey('');
      const rows = await request<Workspace[]>('/api/workspaces');
      setWorkspaces(rows); openWorkspace(rows[0]?.workspace_id ?? ''); setRefresh(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function dismiss(event: FormEvent) {
    event.preventDefault(); if (!detail) return;
    setBusy(true); setError('');
    try {
      await request(base + `/cases/${detail.case_id}/dismiss`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({reason, observation_id: detail.latest_observation_id, fingerprint: detail.fingerprint})});
      setMessage('Disposition recorded. An unchanged finding stays dismissed.'); setRefresh(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function moreCases() {
    if (!cursor) return;
    setBusy(true);
    try {
      const rows = await request<{data: Case[]; next_cursor: string | null}>(base + `/cases?after=${encodeURIComponent(cursor)}`);
      setCases(current => [...current, ...rows.data]); setCursor(rows.next_cursor);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function moreHistory() {
    if (!detail || !timelineCursor) return;
    setBusy(true);
    try {
      const rows = await request<{data: Timeline[]; next_generation: number | null}>(base + `/purchases/${detail.purchase_id}/timeline?before_generation=${timelineCursor}`);
      setTimeline(current => [...current, ...rows.data]); setTimelineCursor(rows.next_generation);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return <>
    <a className="skip" href="#main">Skip to investigation</a>
    <header><div><p className="eyebrow">PAYMENT OPERATIONS / LOCAL DEMO</p><h1>Know what happened.<br/>Recover with evidence.</h1></div>
      <span className="badge">Local development</span></header>
    <main id="main">
      {error && <p className="alert" role="alert">{error}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      {!workspace ? <section className="card login"><h2>Open your workspace</h2><p>This development console uses local fixture identities. Enter the generated demo login key from your private .env file.</p>
        <form onSubmit={login}><label htmlFor="identity">Identity</label><select id="identity" value={subject} onChange={e => setSubject(e.target.value)}>
          {['owner_a','operator_a','viewer_a','owner_b'].map(value => <option key={value}>{value}</option>)}</select>
          <label htmlFor="key">Demo login key</label><input id="key" type="password" autoComplete="off" value={loginKey} onChange={e => setLoginKey(e.target.value)} required/>
          <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form></section> : <>
        <nav aria-label="Workspace controls"><label htmlFor="workspace">Workspace</label><select id="workspace" disabled={busy} value={workspace} onChange={e => openWorkspace(e.target.value)}>
          {workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{w.workspace_id} · {w.role}</option>)}</select>
          <button disabled={busy} onClick={() => setRefresh(r => r + 1)}>Refresh evidence view</button>
          {!csrf && <button disabled={busy} onClick={() => openWorkspace('')}>Sign in for actions</button>}
          <button className="secondary" disabled={busy || !csrf} onClick={async () => {
            try { await request(base + '/sessions/revoke', {method: 'POST', headers: {'X-CSRF-Token': csrf}}); openWorkspace(''); setWorkspaces([]); setCsrf(''); setMessage('Signed out.'); }
            catch (e) { setError((e as Error).message); }
          }}>Sign out</button></nav>
        <p className="muted" role="status">{busy ? 'Loading current workspace…' : 'Current view loaded. Refresh to check for changes.'}</p>
        {coverage && <section aria-labelledby="coverage-title"><div className="section-heading"><h2 id="coverage-title">What we have verified</h2><span className="muted">All registered purchases, including older ones</span></div>
          <div className="metrics">{Object.entries(coverage.evidence_coverage).map(([name,value]) => <div className="metric" key={name}><strong>{value}</strong><span>{words(name)}</span></div>)}</div>
          <div className="card health"><h3>Connection & scan health</h3>
            {health?.connections.map(c => <p key={c.connection_id}><strong>{c.connection_id}</strong> · {c.provider} · {c.environment}</p>)}
            {coverage.runs.map(run => <p key={run.connection_id}>Sweep: {words(run.state)} · {run.scheduled_purchases} purchases scheduled · {run.unbound_purchases} without bounded attempt coverage · {when(run.finished_at)}</p>)}
            {health?.jobs.map(job => <span className="chip" key={job.state}>{words(job.state)} jobs: {job.count}</span>)}
            {health?.receipts.map(receipt => <span className="chip" key={receipt.state}>{words(receipt.state)} receipts: {receipt.count}</span>)}
            <p className="muted">A scheduled scan means reads were queued. It does not confirm they succeeded. Unregistered provider inventory and expired event history are outside this scan.</p></div></section>}
        <div className="investigation"><section aria-labelledby="inbox-title"><div className="section-heading"><h2 id="inbox-title">Case inbox</h2><span className="muted">{cases.length} loaded</span></div>
          {!cases.length && !busy && <div className="card"><h3>No findings yet</h3><p>Successful payments start a two-minute fulfillment grace period. No cases does not guarantee complete evidence; check coverage above.</p></div>}
          <ul className="case-list">{cases.map(c => <li key={c.case_id}><button disabled={busy} className={`case-row ${selected === c.case_id ? 'selected' : ''}`} onClick={() => {setSelected(c.case_id); setMessage('');}}>
            <span className="row-top"><span className="badge">{words(c.state)}</span><span className={isFresh(c) ? 'fresh' : 'unknown'}>{isFresh(c) ? 'Fresh evidence' : 'Evidence uncertain'}</span></span>
            <strong>{words(c.discrepancy_code)}</strong><span className="mono">{c.purchase_id}</span><span>{isFresh(c) ? words(c.current_outcome) : 'awaiting evidence'} · generation {c.generation}</span></button></li>)}</ul>
          {cursor && <button disabled={busy} onClick={moreCases}>Load more cases</button>}</section>
        <section className="card detail" aria-labelledby="detail-title"><h2 id="detail-title" ref={title} tabIndex={-1}>{detail ? 'Investigation' : selected ? 'Loading investigation…' : 'Select a case'}</h2>
          {!detail && <p className="muted">Read the current payment, reversal and business-access facts together.</p>}
          {detail && <><p className="eyebrow">{words(detail.discrepancy_code)} / GENERATION {detail.generation}</p><h3 className="mono">{detail.purchase_id}</h3>
            <p className={isFresh(detail) ? 'notice' : 'alert'}>{isFresh(detail) ? 'Evidence is fresh and complete.' : 'Evidence is stale, incomplete or superseded. No action is eligible.'}</p>
            <p><strong>{isFresh(detail) ? words(detail.current_outcome) : 'awaiting evidence'}</strong> · {isFresh(detail) ? detail.current_reasons.map(words).join(', ') : 'refresh to verify current facts'}</p>
            <dl><dt>Expected purchase</dt><dd>{money(detail.purchase.expected_amount_minor, detail.purchase.currency)} · {detail.purchase.product_id}</dd>
              <dt>Business access</dt><dd>{detail.observation.facts.access ? `${words(detail.observation.facts.access.status)} · revision ${detail.observation.facts.access.revision}` : 'Unknown'}</dd>
              <dt>Reversal history</dt><dd>{detail.observation.facts.refunds.length} refunds · {detail.observation.facts.disputes.length} disputes</dd>
              <dt>Evidence source</dt><dd>{words(detail.observation.source)} · {detail.observation.api_version}</dd></dl>
            <h3>Current payment attempts</h3>{detail.observation.facts.payments.map(payment => <p key={payment.payment_intent_id}><span className="mono">{payment.payment_intent_id}</span><br/>{words(payment.status)} · {money(payment.amount_received_minor, payment.currency)} received</p>)}
            {detail.observation.facts.errors.map((e,i) => <p className="alert" key={i}>{words(e.bundle)}: {words(e.code)}</p>)}
            <h3>Evidence timeline</h3><ol className="timeline">{timeline.map(t => <li key={t.observation_id}><strong>{words(t.outcome)}</strong><span>{when(t.finished_at)} · read generation {t.generation}</span><span>{t.reasons.map(words).join(', ')}</span></li>)}</ol>
            {timelineCursor && <button disabled={busy} onClick={moreHistory}>Load earlier evidence</button>}
            <details><summary>Observation reference</summary><p className="mono">{detail.latest_observation_id}</p><p className="mono">SHA-256 {detail.observation.content_digest}</p><p>Policy: {detail.policy_version}. Financial settlement is not verified by these access reads.</p></details>
            <h3>Record a disposition</h3><p>Dismissal documents an intentional exception. A material change can open a new finding. Access repair approval arrives in Phase 4.</p>
            <form onSubmit={dismiss}><label htmlFor="reason">Disposition reason</label><textarea id="reason" value={reason} onChange={e => setReason(e.target.value)} minLength={5} maxLength={1000} required/>
              <button disabled={busy || !csrf || role === 'viewer' || !isFresh(detail) || !['open','awaiting_evidence'].includes(detail.state)}>Dismiss finding</button></form>
            {!csrf && <p className="muted">This restored session is read-only. Sign in again to obtain an action token.</p>}
            <h3>Recorded decisions</h3>{detail.audit.length ? detail.audit.map((a,i) => <p key={i}><strong>{words(a.action)}</strong> · {a.subject} · {when(a.created_at)}<br/>{a.reason}</p>) : <p className="muted">No disposition recorded.</p>}
          </>}</section></div></>}
    </main><footer>Payment Reliability & Reconciliation Console · Deterministic detection · Human decisions</footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
