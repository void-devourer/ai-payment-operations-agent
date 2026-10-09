export type Workspace = { workspace_id: string; role: string };
export type Case = {
  case_id: string; purchase_id: string; discrepancy_code: string; generation: number;
  state: string; evidence_fresh: boolean; fresh_until: string | null; current_outcome: string; current_reasons: string[];
  latest_observation_id: string; fingerprint: string; updated_at: string; policy_version: string;
};
export type Window = { started_at: string; finished_at: string; complete: boolean };
export type Facts = {
  scope: { account_id: string; environment: string }; payments: { payment_intent_id: string; status: string; amount_received_minor: number; currency: string }[];
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

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    if (response.status === 401) throw new Error('Session expired. Sign in again.');
    if (response.status === 403) throw new Error('This identity cannot perform that action.');
    if (response.status === 409) throw new Error('Evidence or case changed. Refresh before trying again.');
    throw new Error(`Request failed (${response.status}). Retry after checking service health.`);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
