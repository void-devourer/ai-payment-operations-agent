import {useEffect} from 'react';
import type {ReactNode} from 'react';
import {date} from './api';
import type {Evidence, Project} from './api';

export function Notice({text, onClose, error = false}: {text: string; onClose: () => void; error?: boolean}) {
  useEffect(() => {if (!text || error) return; const timer = setTimeout(onClose, 8000); return () => clearTimeout(timer);}, [text, error, onClose]);
  return text ? <div className={`scope-notice ${error ? 'is-error' : ''}`} role={error ? 'alert' : 'status'}><span>{text}</span><button type="button" className="icon-button" aria-label="Dismiss message" onClick={onClose}><svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.8"/></svg></button></div> : null;
}
export function Badge({children, tone = ''}: {children: ReactNode; tone?: string}) {return <span className={`scope-badge ${tone}`}>{children}</span>;}
export function Loading({text = 'Loading your project…'}: {text?: string}) {return <div className="scope-loading" role="status"><p>{text}</p><div/><div/><div/></div>;}
export function EvidenceLinks({evidence, project, onSource}: {evidence: Evidence[]; project: Project; onSource: (evidence: Evidence) => void}) {
  return <ul className="source-links">{evidence.map((source, index) => <li key={`${source.message_id}-${index}`}><button type="button" onClick={() => onSource(source)} className="source-link"><span>“{source.quote}”</span><small>View original message{project.messages.find(message => message.message_id === source.message_id) ? ` · ${date(project.messages.find(message => message.message_id === source.message_id)!.created_at)}` : ''}</small></button></li>)}</ul>;
}
export const proposalStatus: Record<string, string> = {draft:'Draft', shared:'Awaiting client decision', accepted:'Accepted', declined:'Declined', superseded:'Replaced by a newer agreement'};
export const invoiceStatus: Record<string, string> = {draft:'Draft', creating:'Creating invoice', unpaid:'Awaiting payment', paid:'Paid', outcome_unknown:'Outcome needs review', failed:'Could not create invoice'};
