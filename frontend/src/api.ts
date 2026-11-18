export type Workspace = { workspace_id: string; role: string };
export type Case = {
  case_id: string; purchase_id: string; discrepancy_code: string; generation: number;
  state: string; evidence_fresh: boolean; fresh_until: string | null; current_outcome: string; current_reasons: string[];
  latest_observation_id: string; fingerprint: string; updated_at: string; policy_version: string;
  provider?: string;
};
export type Window = { started_at: string; finished_at: string; complete: boolean };
export type Facts = {
  scope: { account_id: string; environment: string }; payments: { payment_intent_id?: string; capture_id?: string; order_id?: string; status: string; amount_received_minor?: number; amount_minor?: number; currency: string }[];
  orders?: {order_id: string; status: string; amount_minor: number; currency: string}[];
  reversal_complete?: boolean;
  refunds: {id: string; status: string}[]; disputes: {id: string; status: string}[];
  access: {status: string; revision: number; ever_activated: boolean} | null;
  windows: Record<string, Window>; errors: {bundle: string; code: string}[];
};
export type Observation = { facts: Facts; content_digest: string; source: string; api_version: string; finished_at: string };
export type Detail = Case & { purchase: { expected_amount_minor: number; currency: string; product_id: string }; observation: Observation;
  audit: {subject: string; action: string; reason: string; created_at: string}[] };
export type Timeline = { observation_id: string; generation: number; finished_at: string; outcome: string; reasons: string[]; facts: Facts; source: string };
export type Coverage = {
  scope: string; provider_inventory_backfill: string; event_history_reconstruction: string;
  evidence_coverage: { registered_purchases: number; unobserved: number; incomplete: number; stale: number };
  runs: {connection_id: string; state: string; scheduled_purchases: number; unbound_purchases: number; finished_at: string | null}[];
};
export type Health = { connections: {connection_id: string; environment: string; provider: string}[];
  jobs: {state: string; count: number; oldest_created_at: string}[]; receipts: {state: string; count: number}[] };

export type Session = {subject: string; csrf_token: string; expires_at: string; confirmation_until: string};
let authEpoch = 0;
export const invalidateRequests = () => {authEpoch++;};
export class ApiError extends Error {
  constructor(message: string, public status: number, public retryAfter = 0) {super(message);}
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const epoch = authEpoch;
  const response = await fetch(path, { ...options, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const credentials = body.detail === 'Incorrect credentials';
    if (epoch === authEpoch && response.status === 401 && !credentials && path !== '/api/session') window.dispatchEvent(new Event('session-ended'));
    if (epoch === authEpoch && response.status === 428) window.dispatchEvent(new Event('session-confirmation'));
    const retryAfter = Number(response.headers.get('Retry-After')) || 0;
    const message = credentials ? 'Incorrect credentials. Check your login key and try again.'
      : response.status === 401 ? 'Your session ended. Please sign in.'
      : response.status === 403 ? 'You do not have permission for this action.'
      : response.status === 409 ? 'The case changed. Check the latest records and try again.'
      : response.status === 428 ? 'Confirm your identity before making this change.'
      : response.status === 429 ? `Another check is available in ${retryAfter} seconds.`
      : `Request failed (${response.status}). Please try again.`;
    throw new ApiError(message, response.status, retryAfter);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
