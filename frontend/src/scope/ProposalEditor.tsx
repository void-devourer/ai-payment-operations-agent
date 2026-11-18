import {useState} from 'react';
import type {FormEvent} from 'react';
import {amountMinor} from './api';
import type {Candidate, Evidence, Project, Proposal} from './api';
import type {ScopeData} from './useScopeData';

export function ProposalEditor({project, data, candidate, proposal, onClose, onSaved}: {project: Project; data: ScopeData; candidate?: Candidate; proposal?: Proposal; onClose: () => void; onSaved: () => void}) {
  const [title, setTitle] = useState(proposal?.title ?? candidate?.title ?? '');
  const [description, setDescription] = useState(proposal?.description ?? '');
  const [amount, setAmount] = useState(proposal ? (proposal.amount_minor / 100).toFixed(2) : '');
  const [evidence, setEvidence] = useState<Evidence[]>(proposal?.evidence ?? candidate?.evidence ?? []);
  const [messageId, setMessageId] = useState(project.messages[0]?.message_id ?? '');
  const [quote, setQuote] = useState('');
  const [error, setError] = useState('');
  function addSource() {
    const source = project.messages.find(message => message.message_id === messageId);
    if (!source || !quote.trim() || !source.text.includes(quote.trim())) {setError('Copy the exact words from the selected client message.'); return;}
    if (evidence.length >= 10) {setError('Use up to ten source quotes.'); return;}
    if (evidence.some(item => item.message_id === messageId && item.quote === quote.trim())) {setError('This quote is already attached.'); return;}
    setEvidence([...evidence,{message_id:messageId,quote:quote.trim()}]); setQuote(''); setError('');
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setError('');
    try {
      if (!evidence.length) {setError('Attach at least one exact client message quote before saving.'); return;}
      const body = {title,description,amount_minor:amountMinor(amount),evidence,expected_brief_revision:project.brief_revision,...(proposal ? {expected_version:proposal.version} : {})};
      const result = await data.mutate(proposal ? 'Saving new version' : 'Saving proposal', `/projects/${project.project_id}/proposals${proposal ? '/' + proposal.proposal_id : ''}`, body, proposal ? 'PATCH' : 'POST');
      if (result) onSaved();
    } catch (e) {setError((e as Error).message);}
  }
  return <section className="proposal-editor" aria-labelledby="proposal-editor-title"><div className="scope-section-heading"><h2 id="proposal-editor-title">{proposal ? 'Edit the change proposal' : 'Write a change proposal'}</h2><button type="button" onClick={onClose} disabled={!!data.busy}>Cancel</button></div><p className="scope-muted">Describe the deliverable and choose the additional price. The client will accept this exact version before invoicing.</p>{proposal && <p className="scope-inline-warning">Saving a new version invalidates its existing review link and acceptance.</p>}<form className="scope-form" onSubmit={save}><label htmlFor="proposal-title">Change title</label><input id="proposal-title" value={title} onChange={e => setTitle(e.target.value)} required maxLength={120}/><label htmlFor="proposal-description">What you will deliver</label><textarea id="proposal-description" rows={5} value={description} onChange={e => setDescription(e.target.value)} required maxLength={1000} placeholder="Be specific about what this change adds and what is included."/><label htmlFor="proposal-price">Additional price (USD)</label><div className="price-input"><span>$</span><input id="proposal-price" inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} required placeholder="120.00"/></div><section className="proposal-sources"><h3>Supporting client messages</h3>{evidence.length > 0 && <ul>{evidence.map((source,index) => <li key={`${source.message_id}-${index}`}><blockquote>“{source.quote}”</blockquote><button type="button" className="text-button" onClick={() => setEvidence(evidence.filter((_,position) => position !== index))}>Remove quote</button></li>)}</ul>}<details open={!evidence.length}><summary>Attach a source quote</summary><label htmlFor="proposal-message">Client message</label><select id="proposal-message" value={messageId} onChange={e => {setMessageId(e.target.value); setQuote('');}}>{project.messages.map((message,index) => <option value={message.message_id} key={message.message_id}>Message {index+1}: {message.text.slice(0,65)}</option>)}</select>{messageId && <p className="source-original">{project.messages.find(message => message.message_id === messageId)?.text}</p>}<label htmlFor="proposal-quote">Exact words from this message</label><textarea id="proposal-quote" rows={3} value={quote} onChange={e => setQuote(e.target.value)} maxLength={2000}/><button type="button" onClick={addSource} disabled={!quote.trim() || !messageId || evidence.length >= 10}>Attach quote</button></details></section>{error && <p role="alert" className="field-error">{error}</p>}<div className="form-actions"><button className="primary" disabled={!!data.busy || !evidence.length}>{data.busy || (proposal ? 'Save new version' : 'Save proposal')}</button><button type="button" onClick={onClose} disabled={!!data.busy}>Cancel</button></div></form></section>;
}
