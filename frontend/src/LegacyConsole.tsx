import { useCallback, useEffect, useRef, useState } from 'react';

import type { FormEvent } from 'react';
import { ApiError, invalidateRequests, request } from './api';
import type { Session } from './api';
import { Notice } from './Notice';
import { EvidenceHistory } from './EvidenceHistory';
import type { Case, Coverage, Detail, Health, Timeline, Workspace } from './api';
import './style.css';
import { Repairs } from './Repairs';
import { CheckRecords } from './CheckRecords';

import { label as words, reference } from './labels';
const when = (value: string | null) => value ? new Date(value).toLocaleString() : 'In progress';
const money = (amount: number, currency: string) => currency === 'usd'
  ? new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(amount / 100)
  : `${amount} minor units (${currency.toUpperCase()})`;

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState('');
  const [csrf, setCsrf] = useState('');
  const [checkingSession, setCheckingSession] = useState(true);
  const [confirmationUntil, setConfirmationUntil] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [confirmKey, setConfirmKey] = useState('');
  const [confirmError, setConfirmError] = useState('');
  const closeConfirmError = useCallback(() => setConfirmError(''), []);
  const authVersion = useRef(0);
  const closeError = useCallback(() => setError(''), []);
  const closeMessage = useCallback(() => setMessage(''), []);
  const [subject, setSubject] = useState('owner_a');
  const [loginKey, setLoginKey] = useState('');
  const [cases, setCases] = useState<Case[]>([]);
  const [search, setSearch] = useState('');
  const [caseFilter, setCaseFilter] = useState('all');
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
  const loadedCase = useRef('');
  const loadedCount = useRef(50);
  const role = workspaces.find(w => w.workspace_id === workspace)?.role;
  const base = `/api/workspaces/${encodeURIComponent(workspace)}`;
  const isFresh = (c: Case) => c.evidence_fresh && !!c.fresh_until && Date.parse(c.fresh_until) > now;
  const reload = useCallback(() => setRefresh(r => r + 1), []);
  const visibleCases = cases.filter(c => (caseFilter === 'all' || (caseFilter === 'active'
    ? !['resolved','dismissed'].includes(c.state) : c.state === caseFilter))
    && `${words(c.discrepancy_code)} ${c.purchase_id}`.toLowerCase().includes(search.toLowerCase()));

  function openWorkspace(value: string) {
    loadedCount.current = 50; loadedCase.current = '';
    setCases([]); setCursor(null); setCoverage(null); setHealth(null);
    setSearch(''); setCaseFilter('all');
    setSelected(''); setDetail(null); setTimeline([]); setTimelineCursor(null);
    setWorkspace(value); setMessage(''); setError('');
  }

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const version = authVersion.current;
    async function restore() {
      try {
        const session = await request<Session>('/api/session', {signal: controller.signal});
        const rows = await request<Workspace[]>('/api/workspaces', {signal: controller.signal});
        if (controller.signal.aborted || version !== authVersion.current) return;
        setCsrf(session.csrf_token); setSubject(session.subject);
        setConfirmationUntil(Date.parse(session.confirmation_until));
        setWorkspaces(rows); openWorkspace(rows[0]?.workspace_id ?? '');
      } catch (e) {
        if (!controller.signal.aborted && version === authVersion.current && !(e instanceof ApiError && e.status === 401)) setError((e as Error).message);
      } finally {if (!controller.signal.aborted && version === authVersion.current) setCheckingSession(false);}
    }
    void restore();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    function ended() {
      invalidateRequests(); setBusy(false);
      authVersion.current++; openWorkspace(''); setWorkspaces([]); setCsrf('');
      setConfirming(false); setCheckingSession(false); setMessage('Your session ended. Please sign in.');
    }
    function confirmation() {setConfirming(true); setConfirmError('');}
    window.addEventListener('session-ended', ended);
    window.addEventListener('session-confirmation', confirmation);
    return () => {window.removeEventListener('session-ended', ended); window.removeEventListener('session-confirmation', confirmation);};
  }, []);

  useEffect(() => {
    if (!csrf || !workspace) return;
    const controller = new AbortController();
    const version = authVersion.current;
    let renewing = false;
    async function renew() {
      if (document.hidden || renewing) return;
      renewing = true;
      try {
        const session = await request<Session>('/api/session', {signal: controller.signal});
        if (!controller.signal.aborted && version === authVersion.current) {
          setCsrf(session.csrf_token); setConfirmationUntil(Date.parse(session.confirmation_until)); reload();
        }
      } catch (e) {
        if (!controller.signal.aborted && version === authVersion.current) {
          if (e instanceof ApiError && e.status === 401) window.dispatchEvent(new Event('session-ended'));
          else setError((e as Error).message);
        }
      } finally {renewing = false;}
    }
    const lease = setInterval(() => void renew(), 900000);
    const updates = setInterval(() => {if (!document.hidden) reload();}, 15000);
    window.addEventListener('focus', renew);
    return () => {controller.abort(); clearInterval(lease); clearInterval(updates); window.removeEventListener('focus', renew);};
  }, [csrf, workspace, reload]);

  useEffect(() => {
    if (!workspace) return;
    const controller = new AbortController();
    const version = authVersion.current;
    setBusy(true);
    async function loadedCases() {
      const rows = await request<{data: Case[]; next_cursor: string | null}>(base + '/cases', {signal: controller.signal});
      while (rows.next_cursor && rows.data.length < loadedCount.current && !controller.signal.aborted) {
        const next = await request<{data: Case[]; next_cursor: string | null}>(base + `/cases?after=${encodeURIComponent(rows.next_cursor)}`, {signal: controller.signal});
        rows.data.push(...next.data); rows.next_cursor = next.next_cursor;
      }
      return rows;
    }
    Promise.all([
      loadedCases(),
      request<Coverage>(base + '/reconciliation', {signal: controller.signal}),
      request<Health>(base + '/integration-health', {signal: controller.signal}),
    ]).then(([rows, scan, integrations]) => {
      if (controller.signal.aborted || version !== authVersion.current) return;
      setCases(rows.data); setCursor(rows.next_cursor); setCoverage(scan); setHealth(integrations);
    }).catch(e => { if (e.name !== 'AbortError' && version === authVersion.current) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [workspace, refresh]);

  useEffect(() => {
    if (!workspace || !selected) { setDetail(null); setTimeline([]); return; }
    const controller = new AbortController();
    const version = authVersion.current;
    const key = `${workspace}/${selected}`;
    const changedSelection = loadedCase.current !== key;
    if (changedSelection) {
      setDetail(null); setTimeline([]); setTimelineCursor(null); setReason('');
      loadedCase.current = key;
    }
    request<Detail>(base + `/cases/${selected}`, {signal: controller.signal}).then(async d => {
      const history = await request<{data: Timeline[]; next_generation: number | null}>(base + `/purchases/${d.purchase_id}/timeline`, {signal: controller.signal});
      return [d, history] as const;
    }).then(([d, history]) => {
      if (controller.signal.aborted || version !== authVersion.current) return;
      setDetail(d); setTimeline(current => {
        if (changedSelection) return history.data;
        const cutoff = history.data.at(-1)?.generation ?? Infinity;
        const earlier = current.filter(row => row.generation < cutoff);
        return [...history.data, ...earlier];
      });
      setTimelineCursor(current => changedSelection || !timeline.length ? history.next_generation : current === null ? null : Math.min(current, history.next_generation ?? current));
      if (changedSelection) title.current?.focus({preventScroll: true});
    }).catch(e => { if (e.name !== 'AbortError' && version === authVersion.current) setError(e.message); });
    return () => controller.abort();
  }, [workspace, selected, refresh]);

  async function login(event: FormEvent) {
    invalidateRequests();
    event.preventDefault(); authVersion.current++; setBusy(true); setError(''); setMessage('');
    try {
      const session = await request<Session>(`/dev/sessions/${subject}`, {method: 'POST', headers: {'X-Demo-Login-Key': loginKey}});
      setCsrf(session.csrf_token); setConfirmationUntil(Date.parse(session.confirmation_until)); setLoginKey('');
      const rows = await request<Workspace[]>('/api/workspaces');
      setWorkspaces(rows); openWorkspace(rows[0]?.workspace_id ?? ''); setRefresh(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function confirmIdentity(event: FormEvent) {
    event.preventDefault(); setBusy(true); setConfirmError('');
    try {
      const session = await request<{confirmation_until: string}>(base + '/sessions/confirm', {
        method: 'POST', headers: {'X-CSRF-Token': csrf, 'X-Demo-Login-Key': confirmKey},
      });
      setConfirmationUntil(Date.parse(session.confirmation_until)); setConfirmKey(''); setConfirming(false);
      setError(''); setMessage('Identity confirmed. You can continue with the change.');
    } catch (e) {setConfirmError((e as Error).message);} finally {setBusy(false);}
  }

  async function dismiss(event: FormEvent) {
    event.preventDefault(); if (!detail) return;
    setBusy(true); setError('');
    try {
      await request(base + `/cases/${detail.case_id}/dismiss`, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
        body: JSON.stringify({reason, observation_id: detail.latest_observation_id, fingerprint: detail.fingerprint})});
      setMessage('Case closed. Your reason has been recorded.'); setRefresh(r => r + 1);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function moreCases() {
    if (!cursor) return;
    setBusy(true);
    try {
      const rows = await request<{data: Case[]; next_cursor: string | null}>(base + `/cases?after=${encodeURIComponent(cursor)}`);
      loadedCount.current += rows.data.length;
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
      <Notice text={error} onClose={closeError} error/>
      <Notice text={message} onClose={closeMessage}/>
      {checkingSession ? <section className="panel login" role="status">Restoring your session…</section> : !workspace ? <section className="panel login"><h2>Sign in</h2><p>Choose your demo identity and enter your login key.</p>
        <form onSubmit={login}><label htmlFor="identity">Identity</label><select id="identity" value={subject} onChange={e => setSubject(e.target.value)}>
          {['owner_a','operator_a','viewer_a','owner_b'].map(value => <option key={value} value={value}>{words(value)}</option>)}</select>
          <label htmlFor="key">Demo login key</label><input id="key" type="password" autoComplete="off" value={loginKey} onChange={e => setLoginKey(e.target.value)} required/>
          <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form></section> : <>
        <div className="workspace-bar"><div className="workspace-picker"><label htmlFor="workspace">Workspace</label><select id="workspace" disabled={busy} value={workspace} onChange={e => openWorkspace(e.target.value)}>
          {workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{words(w.workspace_id)} · {words(w.role)}</option>)}</select></div>
          <div className="workspace-actions"><button className="secondary" disabled={busy} onClick={async () => {
            invalidateRequests();
            authVersion.current++; setBusy(true); setError(''); setMessage('');
            try {
              await request(base + '/sessions/revoke', {method: 'POST', headers: {'X-CSRF-Token': csrf}});
              openWorkspace(''); setWorkspaces([]); setCsrf(''); setConfirming(false); setMessage('Signed out.');
            } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
          }}>Sign out</button></div></div>
        {confirming && <section className="panel confirm-panel" aria-labelledby="confirm-title"><h2 id="confirm-title">Confirm your identity</h2>
          <p>Enter your login key to approve access changes or close a case. Your workspace stays open.</p>
          <Notice text={confirmError} onClose={closeConfirmError} error/>
          <form onSubmit={confirmIdentity}><label htmlFor="confirm-key">Demo login key</label><input id="confirm-key" type="password" value={confirmKey} onChange={e => setConfirmKey(e.target.value)} required/>
          <div className="decision-actions"><button disabled={busy}>Confirm identity</button><button type="button" className="secondary" onClick={() => {setConfirming(false); setConfirmKey('');}}>Cancel</button></div></form></section>}
        <nav className="page-nav" aria-label="Console sections"><button aria-current={page === 'cases' ? 'page' : undefined} onClick={() => setPage('cases')}>Cases</button><button aria-current={page === 'health' ? 'page' : undefined} onClick={() => setPage('health')}>Integration health</button></nav>
        <p className="view-status muted" role="status">{busy ? 'Updating records…' : 'Records update automatically.'}</p>
        {page === 'health' ? <section className="health-page" aria-labelledby="health-title"><h2 id="health-title">Integration health</h2><p className="muted">Coverage and processing status for this workspace.</p>
          {coverage && <><section className="panel"><h3>Evidence coverage</h3><dl className="metrics">{Object.entries(coverage.evidence_coverage).map(([name,value]) => <div key={name}><dt>{words(name)}</dt><dd>{value}</dd></div>)}</dl><p className="muted">Includes all registered purchases, including older ones. Unregistered provider inventory and expired event history are outside this scan.</p></section>
          <section className="panel"><h3>Connections</h3>{health?.connections.length ? health.connections.map(c => <div className="record" key={c.connection_id}><strong className="mono">{c.connection_id}</strong><p>{c.provider} · {c.environment}</p></div>) : <p className="muted">No connections available.</p>}</section>
          <section className="panel"><h3>Reconciliation scans</h3>{coverage.runs.length ? coverage.runs.map(run => <div className="record" key={run.connection_id}><strong>{words(run.state)}</strong><dl><dt>Connection</dt><dd className="mono">{run.connection_id}</dd><dt>Purchases scheduled</dt><dd>{run.scheduled_purchases}</dd><dt>Unbounded attempts</dt><dd>{run.unbound_purchases}</dd><dt>Finished</dt><dd>{when(run.finished_at)}</dd></dl></div>) : <p className="muted">No scans recorded.</p>}<p className="muted">Scheduled reads are queued work. They do not confirm successful verification.</p></section>
          <div className="health-columns"><section className="panel"><h3>Processing jobs</h3>{health?.jobs.length ? <dl>{health.jobs.map(job => <div className="stat-row" key={job.state}><dt>{words(job.state)}</dt><dd>{job.count}</dd></div>)}</dl> : <p className="muted">No jobs recorded.</p>}</section><section className="panel"><h3>Webhook receipts</h3>{health?.receipts.length ? <dl>{health.receipts.map(receipt => <div className="stat-row" key={receipt.state}><dt>{words(receipt.state)}</dt><dd>{receipt.count}</dd></div>)}</dl> : <p className="muted">No receipts recorded.</p>}</section></div></>}
        </section> : <div className={`investigation ${selected ? 'has-selection' : ''}`}>
        <section className="panel inbox" aria-labelledby="inbox-title"><div className="section-heading"><h2 id="inbox-title">Case inbox</h2><span className="muted">{cases.length} loaded</span></div>
          {!cases.length && !busy && <div className="empty"><h3>No findings yet</h3><p>Successful payments have a two-minute fulfillment grace period. Check integration health to confirm evidence coverage.</p></div>}
          <p className="inbox-help muted">Open a case to review its payment records, access status and available actions.</p>
          <div className="inbox-filters"><div><label htmlFor="case-search">Search loaded cases</label><input id="case-search" type="search" placeholder="Finding or purchase reference" value={search} onChange={e => setSearch(e.target.value)}/></div><div><label htmlFor="case-filter">Case status</label><select id="case-filter" value={caseFilter} onChange={e => setCaseFilter(e.target.value)}><option value="all">All statuses</option><option value="active">Active cases</option><option value="resolved">Resolved</option><option value="dismissed">Closed with a reason</option></select></div><p className="muted">Filters apply to loaded cases. Load more to search additional records.</p></div>
          {!!cases.length && !visibleCases.length && <p className="inbox-help">No loaded cases match these filters.</p>}
          <div className="inbox-labels" aria-hidden="true"><span>Finding / purchase reference</span><span>Status</span><span>Evidence</span></div><ul className="case-list">{visibleCases.map(c => <li key={c.case_id}><button disabled={busy} className="case-row" onClick={() => {setSelected(c.case_id); setMessage('');}}>
            <span className="case-description"><strong>{words(c.discrepancy_code)}</strong><span className="case-id" title={c.purchase_id}>Purchase {reference(c.purchase_id)}</span></span><span>{words(c.state)}</span><span className="badge">{isFresh(c) ? 'Current' : 'Needs a new check'}</span></button></li>)}</ul>
          {cursor && <div className="list-footer"><button className="secondary" disabled={busy} onClick={moreCases}>Load more cases</button></div>}</section>
        <section className="panel detail" aria-labelledby="detail-title"><button className="secondary back-button" onClick={() => setSelected('')}>Back to cases</button><div className="detail-heading"><h2 id="detail-title" ref={title} tabIndex={-1}>{detail ? words(detail.discrepancy_code) : 'Loading investigation…'}</h2>
          {!detail && <p className="muted">Choose a finding to review payment, reversal and access facts.</p>}
          {detail && <><p><span className="badge">{words(detail.state)}</span> <span className="muted">Purchase {reference(detail.purchase_id)}</span></p><p className="muted">Last checked {when(detail.observation.finished_at)}</p></>}</div>
          {detail && <>
            <section className="detail-section"><div className="finding-heading"><div><h3>{isFresh(detail) ? words(detail.current_outcome) : 'Check the latest records'}</h3>
              <p>{isFresh(detail) ? detail.current_reasons.map(words).join('; ') : 'Get current payment and access records before deciding what to do.'}</p></div>
              <CheckRecords key={detail.case_id} base={base} caseId={detail.case_id} csrf={csrf} role={role} onChanged={reload}/></div>
              {!isFresh(detail) && timeline[0] && <p className="muted">Last finding: {words(timeline[0].outcome)} — {timeline[0].reasons.map(words).join('; ')}</p>}
              <dl className="purchase-summary"><dt>Customer purchased</dt><dd>{words(detail.purchase.product_id)} · {money(detail.purchase.expected_amount_minor, detail.purchase.currency)}</dd>
              <dt>Customer access</dt><dd>{detail.observation.facts.access ? (detail.observation.facts.access.status === 'active' ? 'Available to the customer' : detail.observation.facts.access.status === 'inactive' ? 'Not available to the customer' : words(detail.observation.facts.access.status)) : 'Not confirmed'}</dd>
              <dt>Refunds and disputes</dt><dd>{detail.observation.facts.reversal_complete === false ? 'History is not fully verified' : detail.observation.facts.refunds.length || detail.observation.facts.disputes.length ? `${detail.observation.facts.refunds.length} refunds · ${detail.observation.facts.disputes.length} disputes` : 'None recorded'}</dd></dl>
            {detail.observation.facts.errors.map((e,i) => <p className="alert" key={i}>{words(e.bundle)}: {words(e.code)}</p>)}</section>
            <section className="detail-section"><h3>Payment records</h3>{detail.observation.facts.payments.length ? <div className="payment-records">{detail.observation.facts.payments.map(payment => {
              const id = payment.capture_id ?? payment.payment_intent_id ?? '';
              return <div className="payment-record" key={id}>
              <div><strong>{payment.status === 'succeeded' ? 'Payment received' : words(payment.status)}</strong><p>{money(payment.amount_minor ?? payment.amount_received_minor ?? 0, payment.currency)} {payment.capture_id ? 'capture amount' : 'received'}</p></div>
              <details className="reference-details"><summary>{payment.capture_id ? 'Capture' : 'Payment'} reference {reference(id)}</summary><p className="mono">{id}</p>{payment.order_id && <p>Order <span className="mono">{payment.order_id}</span></p>}</details>
            </div>;})}</div> : <p className="muted">No capture or payment records confirmed.</p>}
              {!!detail.observation.facts.orders?.length && <><h4>PayPal orders</h4>{detail.observation.facts.orders.map(order => <div className="record" key={order.order_id}><strong>{words(order.status)}</strong><p>{money(order.amount_minor, order.currency)} order amount</p><details><summary>Order reference {reference(order.order_id)}</summary><p className="mono">{order.order_id}</p></details></div>)}<p className="muted">An approved order still needs a confirmed capture.</p></>}
            </section>
            {detail.provider === 'paypal' ? <section className="detail-section"><h3>Next action</h3><p>Review the payment and access records. Refund and dispute history needs separate verification before an access repair can be considered.</p></section> : <Repairs detail={detail} base={base} csrf={csrf} role={role} fresh={isFresh(detail)} now={now} confirmedIdentity={confirmationUntil > now} onConfirm={() => setConfirming(true)} onChanged={reload}/>}
            <section className="detail-section"><details className="close-case"><summary>Close without a repair</summary><p>Use this when no action is needed. Record why you are closing the case.</p>
              <form onSubmit={dismiss}><label htmlFor="reason">Reason for closing</label><textarea id="reason" placeholder="Explain why no repair is needed." value={reason} onChange={e => setReason(e.target.value)} minLength={5} maxLength={1000} required/>
              <button disabled={busy || !csrf || role === 'viewer' || confirmationUntil <= now || !isFresh(detail) || !['open','awaiting_evidence','awaiting_approval'].includes(detail.state)}>Close case</button></form>
              {role === 'viewer' ? <p className="muted">An owner or operator can close this case.</p> : confirmationUntil <= now ? <button className="secondary" onClick={() => setConfirming(true)}>Confirm identity to close case</button> : !isFresh(detail) && <p className="muted">Check latest records before closing this case.</p>}
            </details></section>
            <EvidenceHistory timeline={timeline} cursor={timelineCursor} busy={busy} onMore={moreHistory}/>
            <section className="detail-section"><details><summary>Technical references</summary><dl><dt>Purchase reference</dt><dd className="mono">{detail.purchase_id}</dd><dt>Source</dt><dd>{words(detail.observation.source)} · {detail.observation.api_version}</dd><dt>Observation</dt><dd className="mono">{detail.latest_observation_id}</dd><dt>SHA-256</dt><dd className="mono">{detail.observation.content_digest}</dd><dt>Policy</dt><dd>{detail.policy_version}</dd><dt>Access record version</dt><dd>{detail.observation.facts.access?.revision ?? 'Unknown'}</dd></dl><p className="muted">These records confirm payment and application access, not bank settlement.</p></details></section>
            <section className="detail-section"><h3>Case activity</h3>{detail.audit.length ? <>{detail.audit.slice(0,5).map((a,i) => <div className="record" key={i}><strong>{words(a.action)}</strong><p className="muted">{words(a.subject)} · {when(a.created_at)}</p><p>{a.action === 'repair_result' ? words(a.reason) : a.reason}</p></div>)}
              {detail.audit.length > 5 && <details><summary>Earlier activity ({detail.audit.length-5} loaded)</summary>{detail.audit.slice(5).map((a,i) => <div className="record" key={i}><strong>{words(a.action)}</strong><p className="muted">{words(a.subject)} · {when(a.created_at)}</p><p>{a.action === 'repair_result' ? words(a.reason) : a.reason}</p></div>)}</details>}
            </> : <p className="muted">No operator activity yet.</p>}</section>
          </>}</section></div>}</>}
    </main><footer>Payment Operations · Local development console</footer>
  </>;
}


