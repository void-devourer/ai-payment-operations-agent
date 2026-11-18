export type Evidence = {message_id: string; quote: string};
export type Message = {message_id: string; text: string; created_at: string};
export type Candidate = {title: string; classification: 'included' | 'addition' | 'unclear'; rationale: string; evidence: Evidence[]};
export type Analysis = {analysis_id: string; mode: 'sample' | 'openai' | 'gemini'; summary: string; candidates: Candidate[]; created_at: string};
export type Proposal = {proposal_id: string; title: string; description: string; amount_minor: number; currency: string; version: number; brief_revision: number; status: string; proposal_digest: string; evidence: Evidence[]; accepted_by: string | null; accepted_at: string | null; created_at: string};
export type Invoice = {invoice_id: string; proposal_id: string; provider: string; provider_invoice_id: string | null; status: string; amount_minor: number; currency: string; payment_url: string | null; last_error: string | null; created_at: string};
export type Agreement = {proposal_snapshot: {brief: string; project_name: string; client_name: string; proposal: Pick<Proposal,'proposal_id'|'title'|'description'|'amount_minor'|'currency'|'version'|'brief_revision'|'proposal_digest'|'evidence'>}; decision: string; decision_name: string; decided_at: string; created_at: string; revoked_at: string | null};
export type Project = {project_id: string; name: string; client_name: string; client_email: string; brief: string; brief_revision: number; base_amount_minor: number; currency: string; demo: boolean; created_at: string; messages: Message[]; analysis: Analysis | null; proposals: Proposal[]; invoices: Invoice[]; agreements: Agreement[]; events: {event_id: string; kind: string; text: string; created_at: string}[]};
export type ProjectSummary = Pick<Project, 'project_id' | 'name' | 'client_name' | 'client_email' | 'brief' | 'brief_revision' | 'base_amount_minor' | 'currency' | 'demo' | 'created_at'>;
export type ScopeConfig = {analysis: {mode: string}; invoice: {mode: string}; sample_available: boolean};
export type Review = {project_name: string; client_name: string; brief: string; proposal: Proposal; expires_at: string};
export type Share = {share_url: string; expires_at: string; proposal_id: string; proposal_version: number};

export class ScopeError extends Error {
  constructor(message: string, public status: number, public retryAfter = 0) {super(message);}
}
let sessionEpoch = 0;
export const invalidateScopeRequests = () => {sessionEpoch++;};

const ERROR_COPY: Record<string, string> = {
  gemini_not_configured: 'Gemini is not configured. Ask the workspace owner to set its server-side API key and model. You can still write proposals yourself.',
  gemini_authentication_failed: 'Gemini rejected the API credentials or access permissions. Ask the workspace owner to check the API key.',
  gemini_rate_limited: 'Gemini’s API quota or rate limit has been reached. Check the free-tier allowance before trying again. Your messages are saved.',
  gemini_unavailable: 'Gemini could not complete this review. Your messages are saved; try again later or review them yourself.',
  gemini_network_error: 'The server could not reach Gemini. Your messages are saved; try again later.',
  gemini_timeout: 'Gemini took too long to respond. Your messages are saved; try again later.',
  openai_unavailable: 'OpenAI could not complete this review. Your source messages are saved. Try again later or review them yourself.',
  openai_quota_exhausted: 'AI review is unavailable because the OpenAI API credit or spending limit has been reached. Ask the workspace owner to check API billing. Your messages are saved; you can still write a proposal yourself.',
  openai_rate_limited: 'OpenAI is temporarily limiting review requests. Wait before trying again. Your messages are saved.',
  analysis_unavailable: 'AI review is not available. You can still review messages and write a proposal yourself.',
  openai_not_configured: 'OpenAI is not configured. You can review messages and write a proposal yourself.',
  analysis_input_budget: 'This conversation exceeds the AI review limit. Review the messages manually, or start a new project with a shorter conversation. Nothing was silently cut off.',
  analysis_input_invalid: 'The conversation cannot be reviewed in its current form. Check the brief and source messages, or review them manually.',
  sample_changed: 'The sample review only works with the original sample brief and messages. Use OpenAI or review these changes yourself.',
  sample_requires_unchanged_example: 'The sample review only works with the original sample brief and messages. Use OpenAI or review these changes yourself.',
  analysis_citation_invalid: 'The AI response could not be tied to the original messages, so it was not saved. Review the conversation yourself or try again.',
  analysis_output_invalid: 'The AI response did not pass validation and was not saved. Your original messages are unchanged.',
  analysis_incomplete: 'The AI review did not finish. Your messages are saved; try again or review them yourself.',
  analysis_refused: 'The AI service did not provide a review. You can still write a proposal using the source messages.',
  proposal_not_accepted: 'The client needs to accept this proposal before you can create an invoice.',
  stale_proposal: 'This proposal changed. Open its latest version and try again.',
  stale_brief: 'The project brief changed. Review the current agreement before continuing.',
  review_expired: 'This review link has expired. Ask the freelancer for a new link.',
  review_unavailable: 'This review link is no longer available. Ask the freelancer for a current link.',
};

export async function scopeRequest<T>(path: string, options: RequestInit = {}, isPublic = false): Promise<T> {
  const epoch = sessionEpoch;
  const response = await fetch(path, {...options, credentials: isPublic ? 'omit' : 'same-origin', cache: 'no-store', referrerPolicy: 'no-referrer'});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const raw = typeof body.detail === 'string' ? body.detail : typeof body.detail?.code === 'string' ? body.detail.code : '';
    const incorrectCredentials = raw === 'Incorrect credentials';
    if (epoch === sessionEpoch && !isPublic && response.status === 401 && !incorrectCredentials && path !== '/api/session' && !path.startsWith('/dev/sessions/')) window.dispatchEvent(new Event('session-ended'));
    if (epoch === sessionEpoch && !isPublic && response.status === 428) window.dispatchEvent(new Event('session-confirmation'));
    const message = ERROR_COPY[raw] || (response.status === 401 ? (incorrectCredentials || path.startsWith('/dev/sessions/') ? 'Incorrect login key. Check your credentials and try again.' : 'Your session ended. Please sign in again.')
      : response.status === 403 ? 'You do not have permission to make this change.'
      : response.status === 404 || response.status === 410 ? (isPublic ? 'This review link is unavailable or expired. Ask the freelancer for a new one.' : 'This project could not be found. Return to your project list.')
      : response.status === 409 ? (isPublic ? 'The proposal changed or a decision was already recorded. Ask for a current review link.' : 'This record changed. Refresh the project and review the latest version before trying again.')
      : response.status === 428 ? 'Confirm your identity, then repeat the action.'
      : response.status === 429 ? 'Too many requests. Wait a moment before trying again.'
      : response.status === 422 ? 'Check the form fields. Text, prices or source quotes may be invalid.'
      : response.status === 503 ? 'This provider is not configured or is temporarily unavailable. Your project is still saved.'
      : 'The request could not be completed. Please try again.');
    throw new ScopeError(message, response.status, Math.max(0, Number(response.headers.get('Retry-After')) || 0));
  }
  return response.status === 204 ? undefined as T : response.json();
}

export const money = (amount: number, currency = 'usd') => new Intl.NumberFormat('en-US', {style: 'currency', currency: currency.toUpperCase()}).format(amount / 100);
export const date = (value: string) => new Date(value).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'});
export function amountMinor(value: string) {
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(value.trim())) throw new Error('Enter a positive amount with no more than two decimal places.');
  const [whole, fraction = ''] = value.trim().split('.');
  const amount = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
  if (!amount) throw new Error('The amount must be greater than zero.');
  if (amount > 100000000) throw new Error('The amount cannot exceed $1,000,000.00.');
  return amount;
}

export function publicToken() {
  const match = /^#\/review\/([A-Za-z0-9_-]+)$/.exec(window.location.hash);
  return match?.[1] ?? null;
}

export function safePaymentUrl(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && (url.hostname === 'www.sandbox.paypal.com' || url.hostname === 'sandbox.paypal.com') && !url.username && !url.password ? url.href : null;
  } catch {return null;}
}
