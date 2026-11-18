import {date, money} from './api';
import type {Agreement} from './api';
import {Badge} from './Components';

export function AgreementHistory({agreements}: {agreements: Agreement[]}) {
  if (!agreements.length) return null;
  return <details className="agreement-history"><summary>Previous client decisions ({agreements.length})</summary><p className="scope-muted">Each record preserves the exact proposal and project brief the client reviewed. Current proposals may have changed since then.</p>{agreements.map((agreement,index) => {
    const snapshot = agreement.proposal_snapshot;
    const proposal = snapshot.proposal;
    return <section className="historical-agreement" key={`${proposal.proposal_id}-${proposal.version}-${index}`}><div className="scope-section-heading"><h3>{proposal.title}</h3><Badge tone={agreement.decision === 'accepted' ? 'positive' : 'warning'}>{agreement.decision === 'accepted' ? 'Accepted' : 'Declined'}</Badge></div><p>{agreement.decision_name} · {date(agreement.decided_at)} · version {proposal.version}</p><p className="preserve-lines">{proposal.description}</p><dl className="brief-price"><dt>Additional price at this decision</dt><dd>{money(proposal.amount_minor,proposal.currency)}</dd></dl><h4>Original brief at this decision</h4><p className="preserve-lines">{snapshot.brief}</p><h4>Supporting client messages</h4>{proposal.evidence.map((source,position) => <blockquote key={position}>{source.quote}</blockquote>)}{agreement.revoked_at && <p className="scope-muted">The review link was later revoked. This decision record is preserved.</p>}</section>;
  })}</details>;
}
