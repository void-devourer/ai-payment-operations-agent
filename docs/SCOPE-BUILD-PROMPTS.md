# PROMPT 1 — PLAN

Build Scope & Pay for direct-client freelancers: versioned brief → conversation
review → edited change proposal → explicit client acceptance → invoice/payment.
Use PRODUCT.md and the approved idea-1 research. Preserve FastAPI/PostgreSQL/React,
local sessions, RLS and historical operations. Define separate scope project,
brief revision, source message, analysis, proposal, acceptance, invoice and event
models. AI citations must reference authorized input; AI cannot set prices or
record consent. Prices use integer minor units. Acceptance is a capability link
bound to an immutable version, expiring and revocable. Edits invalidate prior
acceptance. Plan tenant, viewer, CSRF, stale-version, duplicate and uncertain-write
tests. Keep local sample review/invoices explicit; never claim live AI or PayPal
acceptance without credentials. Produce a compact API contract and phased plan.

# PROMPT 2 — BUILD

Execute the complete visible workflow, with a responsive classic project workspace
and client review screen. Support creation, brief changes, messages, source-linked
review, editable line items, sharing, acceptance and rejection, local invoice demo,
PayPal sandbox draft creation and invoice-status reads. Implement a real bounded
OpenAI Responses structured-output adapter with strict source validation and an
explicit curated-sample path, not a pretend AI fallback. Preserve exact accepted
payloads, tenant isolation and append-only events. Only an explicitly configured
PayPal sandbox adapter may create drafts; uncertain writes must not blindly repeat.
Do not send invoices/emails or move real money during development. Keep the old
console accessible under /operations. Add migrations, focused public-interface
tests, run instructions, credential templates and an executable local demo.

# PROMPT 3 — REVIEW, TEST AND IMPROVE

Review implementation against the workflow and documented source contracts.
Exercise tenant leakage, forged/expired acceptance links, double acceptance,
stale edits, duplicate invoices, timeout/restart recovery, wrong provider binding,
AI injection, unsupported citations, ambiguous consent and missing credentials.
Run unit and isolated PostgreSQL tests, frontend build and relevant regressions.
Inspect the actual desktop and mobile UI in a bounded pass; correct material
usability and accessibility issues. Record measured results, remaining account/API
gates and deployment requirements. Update product/design/domain documentation.
No public release, real invoice sending, model spending or Git publication without
the appropriate existing authorization and credentials.
