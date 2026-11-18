import {useEffect, useState} from 'react';
import type {FormEvent} from 'react';
import {date, money, scopeRequest} from './api';
import type {Review} from './api';
import {Badge, Loading} from './Components';

export function ClientReview({token}: {token: string}) {
  const [review, setReview] = useState<Review | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [decision, setDecision] = useState('');
  const headers = {Authorization:`Bearer ${token}`};
  useEffect(() => {
    const controller = new AbortController();
    void scopeRequest<Review>('/api/scope/review', {headers,signal:controller.signal}, true).then(value => {setReview(value); if (['accepted','declined'].includes(value.proposal.status)) setDecision(value.proposal.status);}).catch(e => {if (!controller.signal.aborted) setError(e.message);}).finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => controller.abort();
  }, [token]);
  async function decide(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!review || !confirmed) return;
    const submitted = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const choice = submitted?.value;
    if (!choice || !['accepted','declined'].includes(choice)) return;
    setBusy(true); setError('');
    try {
      const result = await scopeRequest<{status:string}>('/api/scope/review/decision', {method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({decision:choice,name,proposal_version:review.proposal.version,proposal_digest:review.proposal.proposal_digest})}, true);
      setDecision(result.status);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  return <div className="scope-app public-review"><header className="scope-header"><a href="/" className="scope-brand">Scope &amp; Pay</a><span>Client review</span></header><main className="client-review-main" id="scope-main">{loading ? <Loading text="Opening your change proposal…"/> : !review ? <section className="scope-empty"><h1>This review link is unavailable</h1><p role="alert">{error || 'Ask the freelancer for a current review link.'}</p></section> : <><div className="client-review-heading"><h1>A change to {review.project_name}</h1><p>Prepared for {review.client_name}. Review the additional work and price before choosing.</p></div><div className="client-agreement"><section className="client-proposal"><div className="scope-section-heading"><h2>{review.proposal.title}</h2><Badge>Version {review.proposal.version}</Badge></div><p className="preserve-lines">{review.proposal.description}</p><dl className="proposal-price"><dt>Additional price</dt><dd>{money(review.proposal.amount_minor,review.proposal.currency)}</dd></dl><h3>Messages supporting this change</h3>{review.proposal.evidence.map((source,index) => <blockquote key={index}>{source.quote}</blockquote>)}<details className="client-original"><summary>Read the original project brief</summary><p className="preserve-lines">{review.brief}</p></details><details className="agreement-reference"><summary>Agreement reference</summary><p>This decision applies to proposal version {review.proposal.version}.</p><code>{review.proposal.proposal_digest}</code></details></section><section className="client-decision">{decision ? <><Badge tone={decision === 'accepted' ? 'positive' : 'neutral'}>{decision === 'accepted' ? 'Accepted' : 'Declined'}</Badge><h2>{decision === 'accepted' ? 'Your agreement is recorded.' : 'Your decision is recorded.'}</h2><p>{decision === 'accepted' ? 'The freelancer can now prepare an invoice for this exact change and amount.' : 'The freelancer can revise the proposal and send you a new review link.'}</p><p className="scope-muted">Accepting a proposal does not charge a payment method.</p></> : <><h2>Your decision</h2><p>Accept only if the work and additional price match what you agree to.</p><form className="scope-form" onSubmit={decide}><label htmlFor="client-review-name">Your full name</label><input id="client-review-name" autoComplete="name" required maxLength={160} value={name} onChange={e => setName(e.target.value)} disabled={busy}/><label className="checkbox-label" htmlFor="client-review-confirm"><input id="client-review-confirm" type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required disabled={busy}/><span>I have reviewed this version of the proposal, its scope and its additional price.</span></label>{error && <p className="field-error" role="alert">{error}</p>}<button type="submit" className="primary" name="decision" value="accepted" disabled={busy || !confirmed || !name.trim()}>{busy ? 'Recording decision…' : `Accept ${money(review.proposal.amount_minor,review.proposal.currency)} change`}</button><button type="submit" name="decision" value="declined" disabled={busy || !confirmed || !name.trim()}>Decline this proposal</button></form><p className="scope-muted">This link expires {date(review.expires_at)}. Anyone with this private link can review and record the decision; share it carefully.</p></>}</section></div></>}</main><footer className="scope-footer"><span>Scope &amp; Pay</span><span>Review the exact work. Agree to the exact price.</span></footer></div>;
}
