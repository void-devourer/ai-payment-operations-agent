# Payment Reliability & Reconciliation Console

Build plan · updated 2026-10-08 · Phase 1 foundation underway; later gates remain open

## 1. Purpose and project boundaries

Build a console that helps a small SaaS team answer: **a customer paid, so why
does the application still deny the access they purchased?** Detect the
disagreement, present trustworthy evidence, and support a controlled repair.

This is the payment project in `ai-payments`. Data Reliability & Replay belongs
in the user's separate project. Software engineering is the primary portfolio
goal; an evaluated AI investigation assistant is a later capability.

Two outcomes matter:

- Product outcome: reduce the effort and time needed to investigate and resolve
  payment/access discrepancies for an actual business workflow.
- Engineering outcome: demonstrate correct behavior under duplicate events,
  reordered deliveries, concurrent requests, process crashes, and uncertain
  external action outcomes.

Neither outcome is achieved by a diagram, a working happy path, or an unsupported
claim of saved revenue. This plan defines the evidence required to establish them.

## 2. Planning documents and authority

| Document | Purpose |
| --- | --- |
| [PROJECT-DIRECTION.md](PROJECT-DIRECTION.md) | Accepted career priority and project split |
| [CONTEXT.md](CONTEXT.md) | Domain vocabulary only |
| [docs/RESEARCH.md](docs/RESEARCH.md) | Verified provider behavior, sources, and limitations |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Contracts, data model, state transitions, and recovery design |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | Requirements, tests, release gates, and evidence |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Phase 0 exact identity and executable policy contract |
| [docs/IMPLEMENTATION-BACKLOG.md](docs/IMPLEMENTATION-BACKLOG.md) | Owned phased tasks covering all acceptance IDs |
| This file | Product scope, build sequence, operating plan, and deferred work |

`overall context.txt` remains historical brainstorming. Contradictory ideas in it
do not expand the current scope. Resolve conflicts between these planning docs
before coding; update the affected requirements and tests together.

## 3. Users, workflow, and validation

### Primary user

A developer or support/operations operator at a small SaaS business whose payment
provider and application access are separate systems. The paying customer is
affected by an incident but is not the initial console user.

### First supported purchase

One customer buys one product through a **one-time payment** that should activate
an access grant. Use a one-time software license or digital access pass as the
reference application. One provider, one currency per purchase, no currency
conversion, and an explicit product-to-access mapping.

Recurring subscriptions are a later extension: renewal, cancellation, proration,
grace periods, and multiple subscription items require additional policies.
Model purchases and payment attempts separately so multiple attempts do not
imply multiple purchases or access grants.

### Discovery work before claiming product validation

Interview approximately 3–5 developers/operators as an initial learning sample,
not as proof of market size. Ask for a recent anonymized incident: what happened,
which records they inspected, how they repaired it, how long it took, and what
their existing tools already do. Investigate whether the business needs a
separate console or primarily better integration code.

Record the current workflow, desired outcome, accessible evidence, existing
alternatives, privacy constraints, and a measurable baseline. A synthetic demo
may proceed while discovery runs; mark it as a simulation until a pilot exists.
Continue the proposed scope if the workflow has credible evidence. If discovery
contradicts it, revise the problem before expanding features.

### Proposed value beyond the provider dashboard

Join provider facts with the business's purchase, access, and processing records.
Provider dashboards and payout reports already exist. The hypothesis is that
business-context investigation and controlled application-access repair reduce
work the provider dashboard cannot complete alone. Validate this hypothesis.

## 4. Complete first-release workflow

The reference application normally fulfills a successful purchase through its own
idempotent payment-to-access handler. The console observes that workflow. Injected
failures interrupt normal fulfillment; they do not define ordinary product behavior.
Human approval applies to console repairs of exceptions, not every routine purchase.

1. A workspace owner configures the provider connection and business-app adapter.
2. A purchase is registered by the trusted business backend with immutable
   expected customer/product/amount/currency and provider identifiers.
3. Payment events are verified and committed to a durable inbox before success
   is acknowledged. Processing happens in a separate worker.
4. The worker retrieves current provider facts and application access state.
5. A deterministic detector checks whether payment is eligible to grant access.
6. A temporary disagreement enters a configurable waiting period; an overdue
   disagreement becomes a case. Missing evidence is visible as uncertainty.
7. An operator opens the case and sees observed states, timestamps, identifiers,
   failed processing steps, and the evidence supporting the discrepancy.
8. The console proposes `grant_access` only if its explicit policy permits it.
9. An authorized operator approves the exact proposal; approval and enqueueing
   the repair commit together. No separate client-side execute request is needed.
10. The worker refreshes evidence, checks approval validity and access revision,
    then calls the adapter with one stable operation identity.
11. The adapter applies the change atomically with its receipt, or returns an
    existing receipt, a precondition conflict, or an error.
12. The console verifies the result and records the operation and business
    outcome. A timeout can produce `outcome_unknown`, requiring outcome lookup.
13. Independent reconciliation checks discover mismatches even if an event was
    acknowledged and processing later failed, or an event never reached us.

Business resolution must be supported by fresh access evidence, not just a
successful queue task. If someone fixes access independently, reconciliation
can resolve the case without issuing a repair.

## 5. Scope tiers

### Required for the software release

- Minimal reference SaaS application with checkout, normal idempotent fulfillment,
  purchases, and versioned access grants; controlled faults interrupt fulfillment.
- Provider adapter supporting a deterministic simulator and an independently
  verified Stripe sandbox integration when available.
- Multi-workspace memberships, owner/operator/viewer permissions, and tenant
  isolation across records, background jobs, and evidence retrieval.
- Trusted purchase registration and exact identifier mapping; no email-based
  or amount-only fuzzy matching.
- Durable webhook inbox, resumable jobs, retries, dead-job inspection, and
  event/API-version compatibility handling.
- Current payment/refund/dispute evidence and business-app observations.
- Deterministic detection, configurable grace periods, explicit uncertainty,
  and case lifecycle management, including a manual-review finding for a later
  refund/dispute on active or previously repaired access.
- Human-approved access repair, precondition checks, stable operation identities,
  adapter receipts, unknown-outcome recovery, and append-only audit history.
- Bounded periodic reconciliation with visible coverage/freshness.
- Operator console, integration health, evidence timeline, and recovery status.
- Failure simulator, automated acceptance coverage, performance measurements,
  deployment configuration, backup/restore exercise, and operating runbooks.

### Required for the applied-AI extension

- An assistant that retrieves only authorized case evidence and approved policies.
- Structured explanations with evidence references and explicit uncertainty.
- A bounded tool loop, time/token/cost limits, redaction, and isolation from repair
  execution. A deterministic console remains usable when AI is unavailable.
- Frozen evaluation scenarios, adversarial cases, a non-AI baseline, measured
  results, and an enable/disable decision based on those results.

### Later extensions, each with its own gate

1. Read-only order/refund and automatic-payout reconciliation, including actual
   fee/adjustment explanations and business-record mappings.
2. Recurring subscriptions and product entitlement policies after a real user
   identifies the required lifecycle rules.
3. A second provider, such as Razorpay, after the first adapter contract is stable.
4. Notifications to configured business channels with deduplication and privacy
   controls. Sending actual external notifications is separate from this plan.
5. Provider writes such as refunds only after a new threat model, permissions,
   approval policy, idempotency tests, and sandbox proof. The first release has
   no Stripe refund execution endpoint.

### Explicit exclusions

Payment processing/card storage, bank transfers, automatic refund decisions,
tax determination, risk-model replacements, overturning provider account holds,
global currency conversion, a full accounting ledger, universal log ingestion,
generic autonomous agents, and a no-code workflow builder. No microservices,
Kafka, Kubernetes, or sharding requirement without measured need.

## 6. Baseline implementation choices

| Concern | Proposed baseline | Reason |
| --- | --- | --- |
| Backend | Python 3.13, FastAPI, Pydantic | Familiar backend foundation with typed request contracts |
| Database | PostgreSQL 17, psycopg2, versioned SQL migrations | Explicit transactions, RLS, constraints and checksum-verified migration jobs |
| Job execution | Separate worker process using a PostgreSQL jobs table | Durable state without a database/broker dual-write gap |
| Frontend | React, TypeScript, Vite | A usable operator product with explicit state rendering |
| Identity | Managed OIDC; server-managed sessions in secure cookies | Avoid creating a password/identity service |
| Provider SDK | Official Stripe Python SDK behind a provider adapter | Explicit version handling and replaceable fixtures |
| Local environment | Docker Compose: API, worker, PostgreSQL, reference app | Reproducible development and multi-process failure tests |
| Tests | unittest, real-PostgreSQL/HTTP integration scripts, later Playwright | Verify transaction behavior and operator workflows |
| Quality checks | Ruff, Python type checking, TypeScript checks, formatting | Consistent implementation with small reviewable changes |
| Observability | Structured logs, metrics, OpenTelemetry-compatible tracing | Correlate requests, jobs, cases, and operations |
| CI | GitHub Actions once a Git repository/remote exists | Repeatable checks and deployable artifacts |
| AI | One configurable provider SDK behind an isolated interface | Avoid framework dependence and uncontrolled orchestration |

Python runtime dependencies are now pinned in `requirements.lock`. Phase 1's
direct-SQL implementation is described in [docs/PHASE-1.md](docs/PHASE-1.md).
Frontend and hosting choices remain planned; compatibility and their lockfiles
must be verified in their phases. No paid service is provisioned.

No Redis is required initially. Add caching or an external broker only when a
benchmark identifies the specific need and the consistency/recovery design is
updated. Never use stale cached payment evidence to authorize a repair.

## 7. User experience

| Surface | User task and required information |
| --- | --- |
| Workspace setup | Choose connection/environment, confirm integration health, configure grace policy |
| Case inbox | Filter by state, age, product, severity, and assignee; see evidence freshness |
| Case detail | Compare expected purchase, provider payment facts, and observed access |
| Evidence timeline | Distinguish provider event time, receipt time, observation time, and operator actions |
| Repair preview | Show exact target, action, eligibility evidence, policy version, expiry, and preconditions |
| Operation result | Show queued/executing/verified success, conflict, failure, or unknown outcome accurately |
| Integration health | Last successful fetch, backlog age, incompatible events, retries, and reconciliation coverage |
| Audit view | Filter decisions and outcomes; authorized export with sensitive values redacted |
| Simulation lab | Run seeded incidents and inspect recovery in an explicitly simulated environment |

Use clear language: `payment confirmed; access missing` instead of `lost money`.
Do not infer a root cause unless evidence establishes it. Show unknown/stale data
separately from failure and from a healthy state. Display amounts with currency;
store timestamps in UTC and render the operator's locale/timezone.

The UI must support keyboard navigation, visible focus, accessible status labels,
responsive layouts, loading/empty/error states, and meaningful confirmation of
the exact access change. Disable an action visually when appropriate, but enforce
all permissions and preconditions on the server.

## 8. Proposed operating envelope and measurable targets

All numbers below are initial design/test targets, not achieved results or SLAs.
Tune them using a recorded benchmark environment and pilot expectations.

| Setting | Initial proposal |
| --- | --- |
| Seed dataset | 10 workspaces, 5,000 purchases, 20,000 mixed events |
| Local sustained ingest benchmark | 25 simulated webhook requests/second for 10 minutes |
| Short burst | 100 simulated requests/second for 30 seconds |
| Webhook acknowledgement | p95 below 300 ms during the sustained test, excluding simulated network injection |
| DB/queue durability | Every acknowledged valid event remains recoverable after a worker restart |
| Grace period | 120 seconds before treating eligible missing access as overdue |
| Provider evidence freshness | At most 60 seconds old when preparing a proposal; refresh again immediately before execution |
| Approval expiry | 10 minutes, with revalidation even before expiry |
| Job lease/heartbeat | 30-second lease, heartbeat every 10 seconds; test fencing of expired workers |
| Active-case reconciliation | Nominal 60-second scheduling, subject to provider budgets and visible backlog |
| Recovery target | Reclaim an abandoned lease within 60 seconds in the controlled benchmark |
| Tenant fairness | A noisy tenant must not monopolize dispatch; measure other tenants' queue age |

Record CPU, memory, OS, database version, worker count, connection-pool settings,
payload distribution, provider latency, errors, p50/p95/p99, queue age, and
throughput. Load-test local simulators, not Stripe APIs. Treat target misses as
evidence to investigate, not reasons to hide samples or change definitions.

Product metrics: time to detect, investigation time, time to verified recovery,
correct/incorrect discrepancies, stale-evidence warnings, repeated external
effects, and operator effort versus the baseline workflow. Simulated results
cannot establish revenue recovered or production reliability.

## 9. Delivery phases and completion gates

Phases are sequential unless their requirements are independent. Security and
testing evolve from the first phase; they are not end-of-project additions.

### Phase 0 — Evidence, contracts, and feasibility

- Document discovery questions, current workflow, and unvalidated assumptions.
- Finalize the purchase/access policy and exact identifier contract.
- Check genuine sandbox access early: existing Stripe sandbox or currently
  documented anonymous sandbox tooling if available. Verify lifecycle, expiry,
  supported APIs, event shape/version, and key handling before relying on it.
- Keep the deterministic simulator path regardless of sandbox availability.
- Confirm Windows/container prerequisites, identity-provider availability,
  supported runtime versions, and a deployment budget decision.
- Convert all `P0` acceptance items into implementation tasks with explicit owners.

Gate: one written happy-path contract, documented unsafe cases, a runnable
environment strategy, and a clear distinction between simulation and real
provider integration. Lack of a live merchant account must not stop local work.

### Phase 1 — Foundation and reference business application

- Initialize Git if it is still absent; establish small commits and CI checks.
- Set up packages, lockfiles, migrations, Docker Compose, configuration validation,
  and repository documentation.
- Add workspace membership, server-side sessions, roles, tenant-scoped repositories,
  and database isolation rules. Local test identities are development/test only.
- Build the reference app with purchase registration, access read, conditional
  grant operation, and persistent operation receipts. Add a minimal customer
  checkout and normal fulfillment path, with failure controls and process evidence.
- Retry purchase/attempt registration from a reference-app outbox so a console
  outage does not permanently lose trusted mappings. Provider events that arrive
  before registration stay visible and are reconsidered after the binding exists.
- Implement the simulator with independent state and controlled faults.

Gate: a trusted purchase links to a customer/product; the reference app can grant
access once, reject stale preconditions, return a prior receipt, and isolate two
workspaces. Normal successful fulfillment produces no overdue case. Real
PostgreSQL tests run in CI.

### Phase 2 — Durable payment ingestion and evidence

- Implement connection-bound signed webhook ingestion, body/size limits,
  environment checks, durable inbox and job creation in one transaction.
- Add leased workers, retry classification, timeouts, fencing, bounded provider
  concurrency, and dead-job inspection.
- Retrieve provider resources and normalize minimal payment/refund/dispute facts.
- Record API/event versions and quarantine incompatible inputs without interpreting
  them as valid payment success.
- Verify the genuine Stripe sandbox path separately from the simulator.

Gate: duplicates and ordering permutations do not corrupt state; failures before
and after acknowledgement are recoverable. Provider-outage behavior is visible.

### Phase 3 — Detection, reconciliation, and case console

- Implement versioned deterministic policy, grace/freshness rules, exact mappings,
  uncertainty classification, case deduplication, and evidence history. Separate
  payment/reversal/access completeness from optional settlement/fee completeness.
- Build bounded reconciliation with durable progress, explicit incomplete coverage,
  pending-payment revisits, and sweeps of older eligible purchases.
- Ship case inbox/detail, integration health, and a readable evidence timeline.
- Handle an independent manual access fix without creating an unnecessary repair.
- Open a manual-review case for later refund/dispute changes even when access is
  already active; do not close that finding using the missing-access predicate.

Gate: a missing event and an acknowledged-but-unprocessed event are both found;
delayed payments and intentional suspension do not trigger an eligible grant.

### Phase 4 — Approval and repair recovery

- Create immutable proposals, payload-bound approvals, stable operation identities,
  atomic approval/enqueue, permission checks, and single active repair constraints.
- Refresh evidence before execution; reject expired/stale proposals.
- Implement adapter compare-and-set and outcome lookup; persist all attempts.
- Handle the remote-success/local-timeout crash window without issuing a new action.
- Resolve cases only after checking the actual business state.

Gate: the full paid-but-missing-access scenario completes, including concurrent
approvals, a timeout after remote commit, a worker restart, and an intervening
refund/suspension. The console accurately shows an unknown outcome when needed.

### Phase 5 — Software release and engineering evidence

- Complete negative authorization/privacy tests, migration checks, backups/restore,
  process recovery, and resource-limited benchmarks.
- Build the simulation lab and a reproducible demonstration script.
- Deploy an isolated simulated demo with synthetic records and no live provider
  keys or real customer data. Ship runbooks and an honest capability matrix.
- Conduct a supervised sandbox/pilot walkthrough where access is available;
  distinguish pilot evidence from simulator results.

Gate: all P0 software requirements in `docs/ACCEPTANCE.md` pass, the published
demo cannot invoke live actions, and measured limitations are documented.

### Phase 6 — AI investigation extension

- Add a bounded read-only evidence assistant after the deterministic workflow works.
- Version prompts/tool contracts, validate outputs and citations, redact inputs,
  and enforce workspace scope independently of the model.
- Build and freeze the evaluation corpus, run repeated trials, compare with the
  deterministic evidence view, and record failures/cost/latency.

Gate: AI meets the declared evaluation thresholds and improves a measured task;
otherwise retain it as an experimental disabled capability. AI failure must not
block case investigation or deterministic repair.

### Phase 7 — Financial reconciliation extension

- Read actual payment/refund/balance facts; compare business records exactly.
- Explain automatic payout composition, fees, adjustments, and pending balances.
- Support fixture/report-import demonstrations if Reports API sandbox availability
  is limited. Do not label them genuine live-report integration.
- Mark manual/instant payout attribution unavailable where the provider cannot
  establish transaction membership; never invent a composition.

Gate: totals reconcile per currency with source references and explicit coverage;
all rounding, missing-record, and attribution limitations are tested.

## 10. AI contract and evaluation

Allowed tools: `get_case_evidence`, `get_purchase`, `get_access_state`,
`get_payment_evidence`, and `get_policy`. Each tool derives scope from the
authenticated case, not an arbitrary workspace/customer supplied by the model.
No SQL-generation tool and no tool that executes an access grant, refund, or
provider write. Restrict policy retrieval to small approved/versioned documents;
add embeddings only if retrieval experiments justify them.

Output: a summary, observed discrepancy, evidence references, unknowns,
permitted suggested next step, and any deterministic proposal identifier. The
model cannot create executable parameters or claim a repair has occurred.
Server code checks every evidence reference belongs to the authorized case.

Treat customer text, metadata, logs, and retrieved content as untrusted data.
Do not rely on an injection detector to establish authorization. Limit model
calls/tool calls, response size, time, and tokens; enforce an owner-configured
spend ceiling. Record actual token usage and configured price-version assumptions.
The product labels AI suggestions and retains a non-AI investigation path.

Start with at least 100 reviewed scenarios spanning ordinary incidents, uncertainty,
stale evidence, permission boundaries, malicious text, and tool failures. Keep
development cases separate from a frozen holdout. Deterministic checks establish
tool/schema/citation/permission correctness; manual rubric review assesses
grounding and usefulness. LLM judging alone is insufficient.

Proposed release thresholds: zero unauthorized tools/actions or cross-workspace
references, all evidence IDs valid, at least 95% supported explanations in reviewed
holdout responses, and at least 95% appropriate uncertainty/escalation on their
dedicated subset. Publish counts, denominators, trial variability, model/prompt
versions, and failures. Small-sample success does not establish production safety.

## 11. Security, privacy, and operating controls

- Restrict the initial deployment to simulation/sandbox. Live payment writes are
  excluded; deploying real provider connections requires its own reviewed readiness.
- Keep API keys and signing secrets server-side in deployment secrets; redact them
  from logs and prompts. Use least-privilege keys where supported and rotate secrets.
- Validate webhook signatures against raw bytes and the configured connection.
  Keep simulated and real environments segregated; reject mismatched live mode.
- Enforce authentication, membership, role, and target-resource scope on every read
  and action. Audit UI hiding is not an authorization control.
- Use secure/HttpOnly/SameSite cookies, CSRF protection for cookie-authenticated
  mutations, session expiry/revocation, and narrow development CORS origins.
  The provider webhook uses signature authentication, not a browser session.
- Tenant-scoped queries plus row-level security where specified in the architecture;
  run isolation tests with non-owner/non-superuser database roles.
- Permit adapter addresses through deployment-controlled allowlists. Block arbitrary
  user-supplied URLs and access to internal metadata endpoints.
- Store minimal customer identifiers and payment facts; no card numbers/CVCs.
  Mask customer data in the UI where it is unnecessary for the task.
- Proposed retention: raw event payloads up to 7 days, operational evidence up to
  90 days, audit metadata up to 180 days for synthetic/pilot use. Verify needs with
  a pilot before processing real data. These are product defaults, not legal advice.
- Raw-payload expiry must not remove durable action receipts, normalized evidence
  needed for recovery, or outstanding-case references. Deletion/retention jobs
  must preserve consistency and implement explicit redaction where required.
- Encrypt transport and storage using managed platform capabilities; use a vetted
  authenticated-encryption library for stored connection credentials if persisted.
- Restrict replay/dead-job controls and record who requested them. Replaying an
  event is not permission to repeat its external effect.

## 12. Deployment, monitoring, and runbooks

Local Compose runs API, worker, reference app, and PostgreSQL. The reference app
uses a separate database/credentials so repairs cross a real network/commit
boundary. Production-shaped deployment uses API and worker as separate processes
from the same codebase, a managed PostgreSQL service, TLS, and a managed OIDC
provider. Serve the compiled frontend and API under one origin where practical.

Select a hosting provider after confirming region, worker support, database
backups, supported versions, secret storage, and budget. Do not assume a free tier
provides a durable worker or a production SLA. No purchasing or public deployment
is performed as part of creating this plan.

CI gates: lint/type checks, unit and integration tests, tenant/approval negative
tests, migration checks, frontend checks, key end-to-end cases, image build, and
dependency/secret scanning. Run heavier concurrency/chaos/benchmark jobs on a
scheduled or release workflow rather than every small edit.

Observe ingestion failures, oldest queued job, retries/dead jobs, connector errors,
provider throttling, reconciliation lag/coverage, open-case age, stale approvals,
unknown outcomes, adapter conflicts, and actual external effects. Correlate by
workspace, purchase, case, job, and operation ID without logging sensitive payloads.

Required runbooks: provider outage or 429s; invalid signatures; database outage;
stuck jobs/expired leases; incompatible event version; unknown repair outcome;
credential rotation/revocation; tenant-isolation failure; backup restoration;
migration rollback/forward recovery; disabling AI; and disabling repair execution
while preserving read-only investigation.

For the pilot, define recovery-point/recovery-time objectives only after verifying
the host's backup features. Restore a backup into an isolated environment and
verify pending jobs, approvals, receipts, and audit records before claiming recovery.

## 13. Risks and decisions still to establish

| Risk/unknown | Resolution or containment |
| --- | --- |
| No verified customer need yet | Discovery and a supervised workflow trial; label simulation honestly |
| Stripe onboarding/sandbox availability | Early feasibility check, documented expiry/features, simulator fallback |
| Real business app lacks conditional/idempotent repair API | Offer investigation only until the adapter contract is implemented |
| Provider and business app cannot commit atomically together | Fresh checks, conditional writes, post-action verification, reconciliation; disclose residual race |
| External timeout leaves an unknown action outcome | Stable identity and receipt lookup; no fresh operation until resolved |
| Refund/dispute after payment success | Evaluate separate refund/dispute facts; do not treat succeeded status alone as eligibility |
| Missing mapping or stale/incomplete evidence | Await evidence/manual review; never guess the target customer/product |
| Existing tools already solve the workflow adequately | Revise the use case; avoid pretending dashboard duplication is validated value |
| Identity/hosting/package choices change | Verify supported versions and budget at bootstrap; lock dependency versions |
| Scope expands beyond one-time access | Require a separate policy, acceptance criteria, and phase for each extension |

## 14. Portfolio delivery package

Deliver a working synthetic demo, a verified sandbox integration record where
available, architecture and domain docs, source-linked provider constraints,
failure demonstrations, benchmark methodology/results, security boundaries,
AI evaluation results if implemented, a short walkthrough, and an honest list
of limitations. Retain the user discovery/pilot evidence with consent and redaction.

The interview narrative should explain a concrete incident, the correctness
invariant, the failure window, the chosen tradeoff, and how the tests demonstrate
the outcome. Resume claims must use actual measurements and identify simulated
workloads. Never imply Stripe endorsement, production financial scale, or customer
adoption that has not occurred.

## 15. Implementation start condition

Begin with Phase 0 and Phase 1. The first executable vertical slice is:
register a purchase, observe a successful simulated payment, detect missing
access, approve a proposal, grant access through the reference app, and verify
the result. Build this slice before adding AI, payout reports, or a second provider.

This planning work records the implementation sequence for subsequent work.
No application, service, credential, purchase, notification, or live action has
been provisioned or executed while preparing it.
