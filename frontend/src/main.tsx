import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { FormEvent } from 'react';
import { request } from './api';
import type { Case, Coverage, Detail, Health, Timeline, Workspace } from './api';
import './style.css';
import { Repairs } from './Repairs';

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
  const [page, setPage] = useState<'cases' | 'health'>('cases');
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
      title.current?.focus({preventScroll: true});
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
    <a className="skip" href="#main">Skip to content</a>
    <header className="app-header"><div><h1>Payment Operations</h1><p>Review payment findings and their supporting evidence.</p></div><span className="badge">Local demo</span></header>
    <main id="main">
      {error && <p className="alert" role="alert">{error}</p>}
      {message && <p className="notice" role="status">{message}</p>}
      {!workspace ? <section className="panel login"><h2>Open your workspace</h2><p>This local demo uses fixture identities. Enter the generated login key from your private .env file.</p>
        <form onSubmit={login}><label htmlFor="identity">Identity</label><select id="identity" value={subject} onChange={e => setSubject(e.target.value)}>
          {['owner_a','operator_a','viewer_a','owner_b'].map(value => <option key={value}>{value}</option>)}</select>
          <label htmlFor="key">Demo login key</label><input id="key" type="password" autoComplete="off" value={loginKey} onChange={e => setLoginKey(e.target.value)} required/>
          <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form></section> : <>
        <div className="workspace-bar"><div className="workspace-picker"><label htmlFor="workspace">Workspace</label><select id="workspace" disabled={busy} value={workspace} onChange={e => openWorkspace(e.target.value)}>
          {workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{w.workspace_id} · {w.role}</option>)}</select></div>
          <div className="workspace-actions"><button className="secondary" disabled={busy} onClick={() => setRefresh(r => r + 1)}>Refresh evidence</button>
          {!csrf && <button disabled={busy} onClick={() => openWorkspace('')}>Sign in for actions</button>}
          <button className="secondary" disabled={busy || !csrf} onClick={async () => {
            try { await request(base + '/sessions/revoke', {method: 'POST', headers: {'X-CSRF-Token': csrf}}); openWorkspace(''); setWorkspaces([]); setCsrf(''); setMessage('Signed out.'); }
            catch (e) { setError((e as Error).message); }
          }}>Sign out</button></div></div>
        <nav className="page-nav" aria-label="Console sections"><button aria-current={page === 'cases' ? 'page' : undefined} onClick={() => setPage('cases')}>Cases</button><button aria-current={page === 'health' ? 'page' : undefined} onClick={() => setPage('health')}>Integration health</button></nav>
        <p className="view-status muted" role="status">{busy ? 'Loading workspace…' : 'Refresh evidence to check for changes.'}</p>
        {page === 'health' ? <section className="health-page" aria-labelledby="health-title"><h2 id="health-title">Integration health</h2><p className="muted">Coverage and processing status for this workspace.</p>
          {coverage && <><section className="panel"><h3>Evidence coverage</h3><dl className="metrics">{Object.entries(coverage.evidence_coverage).map(([name,value]) => <div key={name}><dt>{words(name)}</dt><dd>{value}</dd></div>)}</dl><p className="muted">Includes all registered purchases, including older ones. Unregistered provider inventory and expired event history are outside this scan.</p></section>
          <section className="panel"><h3>Connections</h3>{health?.connections.length ? health.connections.map(c => <div className="record" key={c.connection_id}><strong className="mono">{c.connection_id}</strong><p>{c.provider} · {c.environment}</p></div>) : <p className="muted">No connections available.</p>}</section>
          <section className="panel"><h3>Reconciliation scans</h3>{coverage.runs.length ? coverage.runs.map(run => <div className="record" key={run.connection_id}><strong>{words(run.state)}</strong><dl><dt>Connection</dt><dd className="mono">{run.connection_id}</dd><dt>Purchases scheduled</dt><dd>{run.scheduled_purchases}</dd><dt>Unbounded attempts</dt><dd>{run.unbound_purchases}</dd><dt>Finished</dt><dd>{when(run.finished_at)}</dd></dl></div>) : <p className="muted">No scans recorded.</p>}<p className="muted">Scheduled reads are queued work. They do not confirm successful verification.</p></section>
          <div className="health-columns"><section className="panel"><h3>Processing jobs</h3>{health?.jobs.length ? <dl>{health.jobs.map(job => <div className="stat-row" key={job.state}><dt>{words(job.state)}</dt><dd>{job.count}</dd></div>)}</dl> : <p className="muted">No jobs recorded.</p>}</section><section className="panel"><h3>Webhook receipts</h3>{health?.receipts.length ? <dl>{health.receipts.map(receipt => <div className="stat-row" key={receipt.state}><dt>{words(receipt.state)}</dt><dd>{receipt.count}</dd></div>)}</dl> : <p className="muted">No receipts recorded.</p>}</section></div></>}
        </section> : <div className={`investigation ${selected ? 'has-selection' : ''}`}>
        <section className="panel inbox" aria-labelledby="inbox-title"><div className="section-heading"><h2 id="inbox-title">Cases</h2><span className="muted">{cases.length} loaded</span></div>
          {!cases.length && !busy && <div className="empty"><h3>No findings yet</h3><p>Successful payments have a two-minute fulfillment grace period. Check integration health to confirm evidence coverage.</p></div>}
          <ul className="case-list">{cases.map(c => <li key={c.case_id}><button disabled={busy} aria-pressed={selected === c.case_id} className={`case-row ${selected === c.case_id ? 'selected' : ''}`} onClick={() => {setSelected(c.case_id); setMessage('');}}>
            <strong>{words(c.discrepancy_code)}</strong><span className="case-id mono" title={c.purchase_id}>{c.purchase_id}</span><span>{words(c.state)} · {isFresh(c) ? 'Fresh' : 'Uncertain'}</span></button></li>)}</ul>
          {cursor && <div className="list-footer"><button className="secondary" disabled={busy} onClick={moreCases}>Load more cases</button></div>}</section>
        <section className="panel detail" aria-labelledby="detail-title"><button className="secondary back-button" onClick={() => setSelected('')}>Back to cases</button><div className="detail-heading"><h2 id="detail-title" ref={title} tabIndex={-1}>{detail ? 'Investigation' : selected ? 'Loading investigation…' : 'Select a case'}</h2>
          {!detail && <p className="muted">Choose a finding to review payment, reversal and access facts.</p>}
          {detail && <><p>{words(detail.discrepancy_code)} · {words(detail.state)}</p><p className="mono">{detail.purchase_id}</p></>}</div>
          {detail && <>
            <section className="detail-section"><h3>Summary</h3><p className={isFresh(detail) ? 'notice' : 'alert'}>{isFresh(detail) ? 'Evidence is fresh and complete.' : 'Evidence is stale, incomplete or superseded. No action is eligible.'}</p>
            <p><strong>{isFresh(detail) ? words(detail.current_outcome) : 'awaiting evidence'}</strong><br/>{isFresh(detail) ? detail.current_reasons.map(words).join(', ') : 'Refresh to verify current facts.'}</p>
            <dl><dt>Expected purchase</dt><dd>{money(detail.purchase.expected_amount_minor, detail.purchase.currency)} · {detail.purchase.product_id}</dd>
              <dt>Business access</dt><dd>{detail.observation.facts.access ? `${words(detail.observation.facts.access.status)} · revision ${detail.observation.facts.access.revision}` : 'Unknown'}</dd>
              <dt>Reversal history</dt><dd>{detail.observation.facts.refunds.length} refunds · {detail.observation.facts.disputes.length} disputes</dd></dl>
            {detail.observation.facts.errors.map((e,i) => <p className="alert" key={i}>{words(e.bundle)}: {words(e.code)}</p>)}</section>
            <section className="detail-section"><h3>Payment attempts</h3>{detail.observation.facts.payments.length ? detail.observation.facts.payments.map(payment => <div className="record" key={payment.payment_intent_id}><p><strong>{words(payment.status)}</strong> · {money(payment.amount_received_minor, payment.currency)} received</p><p className="mono">{payment.payment_intent_id}</p></div>) : <p className="muted">No payment attempts in this observation.</p>}</section>
            <section className="detail-section"><h3>Evidence history</h3><ol className="timeline">{timeline.map(t => <li key={t.observation_id}><strong>{words(t.outcome)}</strong><span>{when(t.finished_at)} · generation {t.generation}</span><span>{t.reasons.map(words).join(', ')}</span></li>)}</ol>
            {timelineCursor && <button className="secondary" disabled={busy} onClick={moreHistory}>Load earlier evidence</button>}
            <details><summary>Technical references</summary><dl><dt>Source</dt><dd>{words(detail.observation.source)} · {detail.observation.api_version}</dd><dt>Observation</dt><dd className="mono">{detail.latest_observation_id}</dd><dt>SHA-256</dt><dd className="mono">{detail.observation.content_digest}</dd><dt>Policy</dt><dd>{detail.policy_version}</dd></dl><p className="muted">Financial settlement is not verified by these access reads.</p></details></section>
            <Repairs detail={detail} base={base} csrf={csrf} role={role} fresh={isFresh(detail)} now={now} onChanged={() => setRefresh(r => r + 1)}/>
            <section className="detail-section"><h3>Disposition</h3><p>Dismiss a finding to document an intentional exception. A material change can open a new finding.</p>
            <form onSubmit={dismiss}><label htmlFor="reason">Disposition reason</label><textarea id="reason" placeholder="Explain why this finding is an intentional exception." value={reason} onChange={e => setReason(e.target.value)} minLength={5} maxLength={1000} required/>
              <button disabled={busy || !csrf || role === 'viewer' || !isFresh(detail) || !['open','awaiting_evidence','awaiting_approval'].includes(detail.state)}>Dismiss finding</button></form>
            {role === 'viewer' ? <p className="muted">Viewers can review evidence. An owner or operator must record a disposition.</p> : !csrf && <p className="muted">Sign in again to record a disposition.</p>}</section>
            <section className="detail-section"><h3>Decision history</h3>{detail.audit.length ? detail.audit.map((a,i) => <div className="record" key={i}><strong>{words(a.action)}</strong><p className="muted">{a.subject} · {when(a.created_at)}</p><p>{a.reason}</p></div>) : <p className="muted">No disposition recorded.</p>}</section>
          </>}</section></div>}</>}
    </main><footer>Payment Operations · Local development console</footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<App/>);
