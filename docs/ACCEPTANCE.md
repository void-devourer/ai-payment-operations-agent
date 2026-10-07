# Requirements and verification plan

Status: planned, not passed. IDs below are stable references for implementation
tasks, tests, and release evidence. Checked planning baseline: 2026-10-07.

## 1. Requirement matrix

`P0` is required for the software release. `AI` is required only if the assistant
is shipped. `FIN` is required for the later financial-reconciliation extension.
No item is complete until the described behavior has reproducible evidence.

| ID | Gate | Requirement | Evidence |
| --- | --- | --- | --- |
| P-01 | P0 | Trusted server registration fixes purchase/customer/product/amount/currency and provider scope | Contract tests; conflicting registration rejected |
| P-02 | P0 | Multiple payment attempts and equal-value distinct purchases remain distinct | Mapping scenarios with identical amounts/customers |
| P-03 | P0 | Normal fulfillment succeeds without console intervention; registration outages recover | Ordinary checkout and reference-app outbox retry scenarios |
| I-01 | P0 | Verify raw webhook bytes, signature recency, destination and environment | Genuine sandbox verification where available plus negative fixtures |
| I-02 | P0 | Commit receipt and job before acknowledging; DB failure remains retryable | Fault before/during commit; inspect persisted rows |
| I-03 | P0 | Duplicate receipts and distinct equivalent effects do not duplicate business changes | Repeated delivery plus separate event IDs |
| I-04 | P0 | Unsupported authentic versions are quarantined and visible | Version fixture and health UI |
| E-01 | P0 | Fetch current provider facts; checkout completion/authorization alone cannot qualify | Delayed-payment and manual-capture fixtures |
| E-02 | P0 | Read refund/dispute facts independently of successful PaymentIntent | Full/partial refund and dispute scenarios |
| E-03 | P0 | Exact scope/binding/freshness/completeness governs eligibility | Missing/mismatched/stale evidence cases |
| E-04 | P0 | Record source, times, versions and content digest of observations | Timeline and observation inspection |
| E-05 | P0 | Track payment/reversal/access completeness separately from optional financial facts | Partial pagination, denied reads, and delayed balance-transaction fixtures |
| D-01 | P0 | Deterministic versioned policy enforces the complete eligibility predicate | Truth-table tests covering allowed and blocked combinations |
| D-02 | P0 | Grace periods separate pending fulfillment from overdue discrepancy | Controlled-clock boundary cases |
| D-03 | P0 | Intentional suspension/revocation never becomes an eligible access repair | Target-state policy tests |
| D-04 | P0 | One active case per discrepancy; dismissal and new generations behave predictably | Concurrent detection and material-change scenarios |
| D-05 | P0 | Later refund/dispute on active access opens a review finding with its own resolution rule | Post-repair reversal; active state cannot silently close the review |
| R-01 | P0 | Independent reconciliation finds missing and acknowledged-but-unprocessed events | Disable/drop ingestion and interrupt processing |
| R-02 | P0 | Partial scans, expired history, 429s, and permission failures are visible | Paginated failure/restart and coverage UI |
| R-03 | P0 | Older purchases remain eligible for bounded refresh after later changes | Refund/dispute introduced on an old purchase |
| A-01 | P0 | Exact immutable proposal has actor, target, policy, evidence, revision, and expiry | Proposal/approval payload inspection |
| A-02 | P0 | Concurrent approval commits one operation/job and audit decision | Concurrent approve requests with real PostgreSQL |
| A-03 | P0 | Execution refreshes eligibility and authorization; stale proposals do not execute | Refund, role revocation, policy change, expiry, target revision change |
| A-04 | P0 | Target applies access and records operation receipt atomically | Target transaction fault injection |
| A-05 | P0 | Same operation/payload returns same receipt; changed payload is rejected | Repeated and concurrent adapter requests |
| A-06 | P0 | Timeout after remote commit produces honest unknown-outcome recovery | Suppress response after target commit; restart worker |
| A-07 | P0 | Resolution is verified business state, distinct from job/operation completion | Independent fix and post-grant suspension cases |
| J-01 | P0 | Leases, heartbeats, fencing, bounded retry and dead-job handling work | Worker-kill and stale-worker scenarios |
| J-02 | P0 | Provider budgets and tenant fairness prevent runaway work | Throttle/noisy-tenant tests and queue-age results |
| S-01 | P0 | Authentication/membership/role checks cover every read/action | Endpoint authorization matrix |
| S-02 | P0 | Tenant isolation covers DB/pool/jobs/adapters/exports/AI evidence | Cross-workspace tests using production-shaped roles |
| S-03 | P0 | Secrets, card data, and unnecessary personal data are absent from UI/logs/prompts | Seed secret canaries and inspect captured sinks |
| S-04 | P0 | Session revocation, CSRF, limits, adapter allowlists, and demo segregation hold | Negative security cases and configuration tests |
| S-05 | P0 | Audit records are append-only to application roles and retention preserves recovery | DB permissions, redaction and retention tests |
| U-01 | P0 | Operators can investigate, approve/reject/dismiss, and see fresh/unknown state | Browser end-to-end walkthrough |
| U-02 | P0 | Keyboard navigation, labels, focus, loading/empty/error states are usable | Browser checks and manual accessibility review |
| O-01 | P0 | Startup validates configuration; health distinguishes readiness from liveness | Missing-secret/database/provider-outage cases |
| O-02 | P0 | Migrations and backup restore preserve pending work and action safety | Fresh/previous-schema migration and isolated restore exercise |
| O-03 | P0 | CI checks and reproducible simulated deployment exist | Clean checkout/build/test/demo procedure |
| O-04 | P0 | Declared benchmark and recovery targets have measured results/limitations | Recorded workload/environment/raw result summary |
| AI-01 | AI | Tools are scoped, read-only, bounded, and output references are verified | Tool/permission/adversarial tests |
| AI-02 | AI | Grounding/uncertainty usefulness is evaluated on reviewed holdout scenarios | Versioned dataset, repeated trials and evaluation report |
| AI-03 | AI | AI outage/cost ceiling leaves deterministic operations usable | Timeout/budget/disabled-provider tests |
| F-01 | FIN | Financial amounts/signs/currencies reflect actual source values | Fixed-currency golden fixtures and available provider observations |
| F-02 | FIN | Automatic payout composition has complete source references | Itemized totals, corrections and missing-data cases |
| F-03 | FIN | Manual/instant attribution and delayed fee data are represented honestly | Unsupported-attribution and asynchronous-capture scenarios |

## 2. Test strategy

- Unit tests: pure eligibility rules, monetary normalization, content digests,
  state transitions, retry classification, and clock/expiry logic.
- Integration tests: actual PostgreSQL constraints/transactions/RLS/job leasing;
  independent reference-app transactions; simulated network faults. SQLite is
  insufficient to verify PostgreSQL locking and RLS behavior.
- Provider contract tests: versioned simulator fixtures and small genuine sandbox
  tests when available. Label them separately in results.
- End-to-end tests: operator login, case investigation, approval, verified repair,
  unknown outcome, permission denial, and integration-health rendering.
- Concurrency/chaos tests: multiple workers, concurrent approvals, stale leases,
  lost responses, restarts, partitions and reconciliation catch-up.
- Performance tests: simulate provider latency and failures locally; keep load
  generation separate from the API/worker measurements.

Use controlled clocks and reproducible seeds. Assert domain outcomes, not only
HTTP status codes or internal function calls. Mocks support predictable faults;
real database/target transactions verify the failure windows mocks can conceal.

## 3. Mandatory scenario catalog

| Scenario | Expected behavior |
| --- | --- |
| Successful payment, no access, grace elapsed | One case and eligible proposal; approved repair verified |
| Successful payment, access already active | No grant; case absent or resolved with supporting access observation |
| Normal checkout/fulfillment without injected fault | Access activates within grace; no overdue exception |
| Console unavailable when the reference app registers a purchase | Mapping outbox retries; early event reconsidered once exact binding exists |
| Normal fulfillment races an approved console repair | One access activation; the other path sees existing state or a precondition conflict |
| Processing/delayed payment, checkout completed | Pending payment; no paid-missing-access grant |
| Authorization awaiting capture | No grant under v1 |
| Payment failed/canceled | No access repair |
| No-charge/free purchase | Unsupported by first policy; no paid inference |
| Wrong currency or received amount | Mismatch requiring investigation; no grant |
| Two legitimate equal-value purchases | Separate bindings; no duplicate-payment inference |
| Multiple successful registered attempts for one purchase | Manual investigation; no automatic refund or ambiguous grant |
| Unknown or conflicting purchase metadata | Await evidence; never guess customer/product |
| Same event delivered repeatedly | One durable receipt, resumable original work, no repeated effect |
| Distinct legitimate updates with same resource/type | Both observed; no permanent blanket suppression |
| Success snapshot arrives after a refund/dispute event | Current facts prevail; no access repair |
| Partial refund while `refunded` is false | Refund history still blocks v1 repair |
| Full/pending/failed refund history | Conservative v1 manual investigation; recorded reason |
| Dispute/history with successful payment | Manual investigation; no claim succeeded implies uncontested funds |
| Incomplete paginated refunds/disputes | Incomplete evidence, not zero refunds/disputes |
| Successful payment with temporarily null balance transaction | Core access eligibility evaluated independently of pending financial evidence |
| Intentional suspension/revocation | No automated reinstatement proposal |
| Missing/stale provider or access response | Await evidence; freshness visible |
| Grace boundary just before/after expiry | Deterministic behavior with controlled clock |
| Concurrent detector runs | One active case per purchase/discrepancy |
| Dismissal with unchanged facts | Recorded suppression until material evidence change |
| Independent operator fixes access | Verify state and resolve without issuing another grant |
| Database unavailable during ingress | No success acknowledgment without durable receipt |
| Crash after receipt commit before worker processing | Job survives and processing resumes |
| Expired worker returns after another worker | Stale lease cannot overwrite local progress |
| Webhook silently omitted | Business-state reconciliation discovers mismatch |
| Event acknowledged, downstream work lost | Reconciliation finds missing outcome independent of delivery flags |
| Provider scan fails on later page | Coverage remains incomplete; checkpoint cannot skip failed records |
| Old purchase later changes | Bounded older-purchase sweep observes it |
| Provider 429/timeout/5xx | Bounded retry and health degradation; no execution from stale evidence |
| Reader permissions revoked | Incomplete evidence and visible configuration failure |
| Simulated/test/live environment mismatch | Reject ingestion/action across environments |
| Invalid/expired signature or oversized body | Reject; no processing job or sensitive payload leak |
| Authentic unsupported event version | Durable quarantine and operator health warning |
| Two actors approve concurrently | One accepted operation; conflict/existing result for the other |
| Client repeats approval after timeout | Same request/payload yields existing operation |
| Approved proposal expires or policy changes | Supersede/expire; require a new reviewed proposal |
| Actor loses membership before dispatch | No execution; recorded authorization failure |
| Refund/suspension/revision changes before execution | Revalidation blocks the outdated action |
| Target accepts action then response is lost | Unknown outcome; lookup finds same receipt; one effect |
| Retry uses same ID with a changed payload | Reject; do not reinterpret the original operation |
| Two different operations race for same access | Target constraint/precondition permits at most one eligible transition |
| Outcome lookup is unavailable | Preserve unknown outcome; no fresh action to escape uncertainty |
| Access revoked after a historically successful grant | Historical receipt remains true; current discrepancy requires new investigation |
| Refund/dispute appears after access is active/repaired | Open review case; active access is not automatic resolution |
| Database restored to before local result recording | Keep execution disabled until reconciliation/receipt lookup establishes state |
| One tenant floods jobs | Other tenants retain measurable access to worker capacity |
| Cross-tenant IDs, pooled sessions, jobs, or exports | Scope violation rejected with no data leakage |
| Simulator controls used on a real connection | Reject; controls cannot mutate real provider/target state |
| Retention deletes expired raw payload | Normalized evidence/outstanding receipts remain sufficient for permitted recovery |

A subsequent provider refund can race after the final pre-execution read. The test
must establish that the system notices and escalates the changed facts; it must
not claim a distributed atomicity guarantee it does not have.

## 4. AI evaluation protocol

Create at least 100 human-reviewed scenarios with known evidence, permissible
conclusions, expected uncertainty, and forbidden actions. Split development and
holdout sets before prompt tuning. Each scenario records its category and
workspace, including forbidden evidence in a different workspace.

Include valid incidents; normal/pending fulfillment; mismatches and insufficient
evidence; refunds/disputes; intentional blocks; stale observations; malicious
metadata/customer text/policies; and tool/provider failures. Ensure every critical
safety class has enough examples to report its own denominator; overall accuracy
must not hide poor performance on a small subset.

Run the frozen holdout multiple times (initial proposal: three independent runs)
for each model/prompt/tool version. Validate schemas, tool boundaries, evidence
IDs, and execution prohibition deterministically. Independently review whether
claims follow evidence, uncertainty is appropriate, and explanations help the
operator. Record disagreements and resolve the rubric before reporting a score.

Compare with a deterministic evidence-summary view, measuring operator correctness
and investigation time when users are available. Without a user study, report
rubric scores and explicitly leave usefulness/time-savings unverified.

The enable gate uses the targets in PLAN.md. Report counts/denominators by class,
variability across runs, invalid tool/schema/citation rates, unsupported claims,
appropriate escalation, latency, token usage, estimated/actual cost assumptions,
and provider failures. No small synthetic evaluation establishes production safety.

## 5. Benchmark and chaos protocol

Use the proposed envelope in PLAN.md and publish changes before running tests.
Seed mixed statuses, repeat deliveries, reordered events, and multiple workspaces.
Use configurable provider/target latency; distinguish local-only paths from paths
that include simulated network reads. Make a fixed correctness oracle from the
seed purchases, provider state, target receipts, and permitted policies.

During the run: capture acknowledgments, unique persisted receipts, jobs, effects,
queue ages, lease recovery, retries, case states, CPU/memory, and DB connections.
After settling the backlog: reconcile all acknowledged distinct events and repair
effects with the oracle. A throughput number without this check is incomplete.

Inject worker loss before/after provider fetch and before/after target commit;
introduce response loss, throttling, and a noisy tenant. Measure recovery time
and whether other tenants progress. Keep small real-sandbox checks separate;
do not direct benchmark traffic at Stripe endpoints.

## 6. Release evidence and stop conditions

Software release requires every P0 item to pass, documented target-contract limits,
an isolated synthetic deployment, migrations/restore proof, and reproducible
benchmark results. Verify the real sandbox path separately and identify any
pending feasibility limitations in the capability matrix.

Stop repair execution, preserve investigation, and investigate if any test/pilot
shows cross-tenant access, an unauthorized effect, conflicting operation identity,
repeated target effect, invalid eligibility treated as valid, secrets in output,
or an unknown outcome shown as verified success. Correct the underlying contract
and add the meaningful regression scenario before re-enabling execution.

AI release and financial reconciliation are separate gates. Failure of AI metrics
does not invalidate a correctly working deterministic software release; it means
the assistant stays disabled/experimental until improved.

Planned final evidence files: a requirement status report with test references,
provider capability matrix, benchmark methodology/results, security boundary
review, restore exercise, runbooks, AI evaluation report if shipped, pilot/user
findings if available, and a demo script. Create them when evidence exists; do
not prefill pass statuses or invented measurements.
