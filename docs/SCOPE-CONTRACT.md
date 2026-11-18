# Scope & Pay — first complete product contract

Accepted 2026-10-15: idea 1, freelancer agreed-scope changes to PayPal invoices.
Implement a full visible local workflow now; external acceptance is separate.

## Architecture and ownership

Existing FastAPI console and PostgreSQL runtime/RLS/session authentication.
New scope tables/models are independent of digital-pass purchase/repair tables.
React owns the new homepage; legacy console remains at /operations. Share links
use `/#/review/<token>` so token fragments are not server/access-log paths.
Client API uses a bearer capability token, expiring/revocable and digest bound.
New invoice jobs run in the existing console worker, separately from read jobs.

## API contract (all operator routes require existing actor/CSRF)

Base: `/api/workspaces/{workspace}/scope`.

- GET /config: `{analysis:{mode},invoice:{mode},sample_available:true}`.
- GET /projects: `{data:[Project]}`. POST /projects: `{name,client_name,
  client_email,brief,base_amount_minor,currency:"usd"}` → Project detail.
- POST /demo: idempotently create this workspace's explicitly labelled sample
  project with a $500 original brief and three message examples. Return detail.
- GET /projects/{id}: Project detail.
- POST /projects/{id}/brief: `{brief,expected_revision}` → detail; increment
  brief_revision and supersede uninvoiced proposals/links. Reject edits that
  could rewrite an existing invoice's agreed scope.
- POST /projects/{id}/messages: `{text}` → detail. Stable IDs and duplicate
  import protection; bounded input, preserve source text and attribution.
- POST /projects/{id}/analysis: `{mode:"sample"|"openai"}` → detail. Sample
  review only applies to the unchanged seeded sample brief/messages; no fake AI
  fallback for arbitrary input. OpenAI unavailable reports a clear 503.
- POST /projects/{id}/proposals: `{title,description,amount_minor,
  evidence:[{message_id,quote}],expected_brief_revision}` → detail.
- PATCH /projects/{id}/proposals/{proposal_id}: same fields plus
  `{expected_version}` → detail; new version invalidates share/acceptance.
- POST /projects/{id}/proposals/{proposal_id}/share: `{expected_version}` →
  `{share_url,expires_at,proposal_id,proposal_version}`. Raw token returned once;
  digest stored. Reissue revokes the old link. No email is sent.
- POST /projects/{id}/invoices: `{proposal_id,mode:"local"|"paypal_sandbox"}` →
  detail; only an accepted current proposal can create one logical invoice.
- POST /projects/{id}/invoices/{invoice_id}/refresh: `{}` → detail.
- POST /projects/{id}/invoices/{invoice_id}/activate: `{}` → detail; explicit,
  recently authenticated operator action on an existing PayPal draft. Queues
  activation with notification suppression, then verifies status and payment URL.
  Unknown outcomes require provider reads; they never trigger blind resending.
- POST /projects/{id}/invoices/{invoice_id}/demo-pay: `{}` → detail;
  local invoices only, labelled simulated payment. Never mutates PayPal.

Public GET `/api/scope/review` → `{project_name,client_name,brief,
proposal,expires_at}`. Only the selected proposal/evidence needed for client review,
never full workspace/project history or unrelated messages.
Public POST `/api/scope/review/decision` → `{status}`; body
`{decision:"accepted"|"declined",name,proposal_version,proposal_digest}`.
Client must explicitly confirm. Exact version/digest, expiry and first decision
are checked transactionally; repeated same decision is idempotent, conflicting
decisions are rejected. No request/model interpretation counts as acceptance.
Both public routes receive `Authorization: Bearer <token>` and omit cookies.
Tokens never appear in API paths or query strings, avoiding access-log exposure.
The share record preserves the complete displayed brief/proposal snapshot so
an accepted version remains reconstructable after a later revision.

## Response models

Project detail: `{project_id,name,client_name,client_email,brief,brief_revision,
base_amount_minor,currency,demo,created_at,messages,analysis,proposals,invoices,events,agreements}`.
Messages: `{message_id,text,created_at}`.
Analysis: `{analysis_id,mode,summary,candidates:[{title,classification:
"included"|"addition"|"unclear",rationale,evidence:[{message_id,quote}]}],created_at}`.
Proposals: `{proposal_id,title,description,amount_minor,currency,version,
brief_revision,status,proposal_digest,evidence,accepted_by,accepted_at,created_at}`.
Invoice: `{invoice_id,proposal_id,provider,provider_invoice_id,status,
amount_minor,currency,payment_url,last_error,created_at}`. States draft, creating,
unpaid, paid, outcome_unknown, failed. `local` and `paypal_sandbox` are explicit.
Events: `{event_id,kind,text,created_at}`.
Agreements: `{proposal_snapshot,decision,decision_name,decided_at,created_at,
revoked_at}`; immutable displayed brief and proposal with its recorded decision.
Available to workspace members, never in unrelated public review responses.

## Adapter interfaces

`backend.app.scope_ai.analyze(brief, messages, *, http, config=None)` returns
`{mode:"openai",summary,candidates}` with validated bounded citations; raises
`AnalysisError(code)`. Reads OPENAI_API_KEY and OPENAI_MODEL only server-side.
`sample_review(brief,messages)` handles exact seeded sample content only.
`configuration()` returns public availability without exposing keys.

`backend.app.scope_invoicing.create_draft(connection,http,payload,key)` and
`read_invoice(connection,http,provider_invoice_id,payload)` return
`{provider_invoice_id,status,amount_minor,currency,payment_url}`.
`InvoiceError(code,uncertain=False,retryable=False)` never echoes upstream bodies.
`activate_invoice(connection,http,provider_invoice_id,payload)` validates a
confirmed draft, activates it with notification suppression, then verifies its
status and payment URL. It is invoked only by the distinct operator-queued job.
Payload: `{invoice_id,recipient_email,client_name,project_name,title,description,
amount_minor,currency}`. Fixed sandbox origin; deterministic invoice number and
reference; exact recipient/amount/currency/reference validation. No redirect or
arbitrary URL credentials. No invoice email is sent by development tools.
If a draft create may have succeeded, persist outcome_unknown and recover or
require review; never blindly create another. Local demo adapters are separate.

## Critical verification

Tenant/viewer/CSRF checks, stale brief/proposal edits, source citation checks,
forged/expired/reissued links, repeat/conflicting client decisions, one invoice
per accepted proposal, isolation of local-vs-real invoice actions, incomplete
provider results and uncertain writes. Test public routes against isolated
PostgreSQL. Inspect the actual desktop and mobile interface before completion.
