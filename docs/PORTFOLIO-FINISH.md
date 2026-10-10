# Bounded local portfolio finishing record

Accepted scope: 2026-10-10. This record distinguishes the synthetic local
deliverable from the original production release gate. No AI, financial
reconciliation, new provider, or TraceBack implementation is included.

## Verification status

83 unit contracts and 50 real PostgreSQL/HTTP regression scenarios passed:
16 ingestion, 12 detection (including two new deadline/backoff checks), 14 repair,
and eight local release/restore scenarios. The clean-project end-to-end benchmark
passed all 24 expected outcomes and preserved all 324 notifications with zero
repairs. The larger historical workload missed its declared window and is
retained below. The isolated crash repeat exposed a resolved-case evidence
defect; the corrected regression and a subsequent real-clock demonstration
passed. The bounded local finishing scope is complete. Original production and
customer-validation requirements remain outstanding. Hosted workflow results
are available in [GitHub Actions](https://github.com/void-devourer/ai-payment-operations-agent/actions/workflows/ci.yml).

### Initial measurement before the grace-deadline change

Actual report: [investigation-baseline.json](benchmarks/investigation-baseline.json).
Resource limits are the existing Compose release profile. One console worker;
Windows 11, Python 3.14.2 host client; 12 new purchases per workspace; 10 extra
workspace-A notifications/sec for 30 seconds; one graceful worker restart.
Before seeding, there were 262 purchases in A, 16 in B, and four isolated
one-purchase test workspaces. Only A/B are serviced by the configured worker.

| Measurement | Workspace A | Workspace B |
| --- | --- | --- |
| Expected outcomes observed | 12/12 | 12/12 |
| Receipt → matching complete evidence p95 | 72.85 s | 28.76 s |
| Receipt → expected policy decision p95, mixed scenarios | 229.99 s | 176.06 s |
| Post-grace missing-access detection maximum (3 cases each) | 103.25 s | 48.80 s |

Webhook acknowledgment p95 was 9.44 ms. The discrepancy decisions include the
required 120-second grace; the post-grace column does not. At three cases per
workspace, nearest-rank p95 is simply the maximum, not a stable tail estimate.
A/B have unequal background inventory: these differences do not isolate the
effect of noisy notifications. Both progressed in this run; no universal fairness
claim follows. Reports preserve individual outcomes and denominators.

The original measurement clients used a psycopg2 connection context, which can
start a transaction even with autocommit enabled. These read-only clients used
READ COMMITTED and no administrator mutations, but could leave an idle
transaction while polling. The scripts now use `closing(connection)` so each
diagnostic SELECT runs in autocommit and the connection closes reliably. The
recorded historical measurements are retained as originally observed.

### Actual post-commit crash demonstration

Report: [recovery-demonstration.json](benchmarks/recovery-demonstration.json).
The generated purchase waited approximately nine minutes for its fresh eligible
case on the original scheduler, reinforcing the refresh limitation. Following
synthetic owner approval, a child exited with code 73 after the target committed.
The target was active at revision 1 while the console had no recorded receipt.
After restarting the worker and waiting for real lease expiry, verified recovery
took 32.08 seconds from the observed crash. There was one dispatch, one lookup,
one verification attempt, and the same target revision and operation identity.
The case resolved. This is one measured controlled run, not a recovery SLA.

### Fresh-stack crash failure and resolved-case correction

Report: [recovery-before-case-refresh-fix.json](benchmarks/recovery-before-case-refresh-fix.json).
The first isolated repeat recovered the immutable receipt with one dispatch and
one lookup, and left the target active at revision 1, but its operation became
`applied_not_recovered`. Background delivery had already resolved the case;
later observations advanced the evidence head without updating that resolved
case. The repair's freshness check therefore rejected the historical observation
despite healthy current access. The declared 600-second recovery window failed.
No second grant or manual database correction was used to conceal it.

Healthy observations now refresh resolved missing-access cases to the current
evidence head while retaining their resolved state. Changed facts and dismissed
cases retain their terminal history; a later discrepancy follows normal new-case
rules. Repeated healthy reads do not append duplicate resolution audit entries.
The process-death regression first resolves the case, publishes another healthy
observation, then recovers the original operation. It failed before the change
at the evidence-freshness assertion. The demonstration also stops promptly at
terminal failure states instead of waiting out the remaining timeout.

Corrected repeat: [recovery-final-repeat.json](benchmarks/recovery-final-repeat.json).
The fixture became eligible after approximately 126 seconds, with no clock
edits. The child exited 73 after commit, and the normal worker verified recovery
33.43 seconds after the observed crash. There was one dispatch, one receipt
lookup and one verification attempt, with the same operation identity and
unchanged active target revision 1. The case resolved. Detection (12), repair
(14, including the strengthened process-death scenario), and release (8)
regressions passed after the correction; the unit suite passed all 83 contracts.
This remains a controlled local observation, not a recovery guarantee.

### Narrow correction verified by PostgreSQL regressions

A complete observation still in the fulfillment grace period now preserves a
queued job due at its durable first-success confirmation plus 120 seconds.
Publication and timer scheduling share the same fenced transaction. A new hint
expedites a queued timer; a retry-wait job retains provider backoff. Every follow-up
reads authoritative evidence again; it does not grant access or bypass approval.
The existing periodic sweep remains the fallback for omitted events/old purchases.

This removes dependence on a new sweep for the known grace boundary, but queued
deadlines can still run late under contention. Reader budgets permit four reads
per second per connection; a one-attempt simulator observation requires payment,
refund, dispute and access reads. Thus an optimistic sustained whole-inventory
refresh cost is about one second per purchase per connection, before pagination,
latency, retries and shared-worker scheduling. An unconditional 60-second refresh
promise for hundreds of purchases would contradict that configured budget.

### Historical-inventory repeat: declared window missed

Actual report: [investigation-historical-limit.json](benchmarks/investigation-historical-limit.json).
After the regression suites, baseline inventory was 323 purchases in A, 30 in B,
and four isolated one-purchase workspaces. It included accumulated integration
fault fixtures and an existing reconciliation backlog; this was not a matched
before/after performance comparison.

All 324 notifications remained durable, with acknowledgment p95 21.24 ms and
zero repairs. By the 600-second post-noise deadline, B had all 12 expected
outcomes, while A had 9/12: all 12 A purchases had complete evidence, but three
missing-access purchases were still inside their grace periods after delayed
first confirmation. The benchmark correctly exited with failure, not a reduced
denominator or an extended deadline.

A's receipt-to-complete-evidence p95 was 603.55 seconds (12/12 measured); B's was
25.58 seconds. A's missing-access post-grace metric was unobserved, not zero.
The queue made progress, but prompt initial observation at that inventory was
not established. The grace-deadline change does not solve initial read capacity.
The local demo cannot promise bounded investigation latency for this historical
workload. A fresh isolated-project measurement is recorded separately below;
it cannot replace or invalidate this failed workload result.

### Clean-checkout local workload

Actual report: [investigation-clean-demo.json](benchmarks/investigation-clean-demo.json).
Ran in the fresh `payment-portfolio-check` project with its own empty database
volume, using the same resource limits and one worker. The original project's
volume was preserved. Workload: 12 new purchases per workspace, three of each
scenario, 300 extra A notifications over 30 seconds and one graceful worker
restart. All 24 expected outcomes passed; 324/324 notifications were durable;
there were zero repairs and no skipped load slots. Acknowledgment p95: 17.96 ms.

| Measurement | Workspace A | Workspace B |
| --- | --- | --- |
| Receipt → matching complete evidence p95 (12 each) | 61.98 s | 28.83 s |
| Receipt → expected policy decision p95, including grace (12 each) | 152.79 s | 145.05 s |
| Missing-access detection after grace, maximum (3 each) | 7.10 s | 14.35 s |

No active read jobs remained at the final snapshot. These are single-run local
observations, not an SLA or a causal speedup over the differently populated
historical runs. The 61.98-second A evidence result also prevents a general
under-60-second claim even for this small workload. The deadline regressions
establish the scheduling mechanism; these measurements establish behaviour only
for the reported inputs, resource limits, and time window.

### Repeat on the corrected implementation

Report: [investigation-final-repeat.json](benchmarks/investigation-final-repeat.json).
The `payment-portfolio-final` project also began with empty inventory and used
the same 24-purchase/300-extra-notification workload, resource limits and graceful
restart. This run includes the resolved-case correction and diagnostic
autocommit change. All 24 expected outcomes passed, all 324 notifications were
durable, no load slots were skipped, and no repairs were created. Acknowledgment
p95 was 19.67 ms; no active read jobs remained at the final snapshot.

| Measurement | Workspace A | Workspace B |
| --- | --- | --- |
| Receipt → matching complete evidence p95 (12 each) | 62.27 s | 29.27 s |
| Receipt → expected policy decision p95, including grace (12 each) | 197.14 s | 147.59 s |
| Missing-access detection after grace, maximum (3 each) | 15.70 s | 11.68 s |

These differences show run-to-run variability rather than a guaranteed latency
improvement. In particular, the worst mixed-policy decision took longer in A
than in the earlier clean run. Both measurements are retained; neither supports
a general under-60-second investigation promise.

## Reproduction commands

Use [RELEASE-RUNBOOK.md](RELEASE-RUNBOOK.md) to start the resource-limited stack.
Run these separately, preserving the existing database volume:

```powershell
python scripts/benchmark_investigation.py --per-workspace 12 --noisy-seconds 30 --noisy-rate 10 --restart-worker
python scripts/demo_recovery.py
python -m unittest discover -s tests/unit
python scripts/check_phase4.py
python scripts/check_phase5.py
python scripts/check_docs.py
```

The benchmark reads diagnostic tables without administrator mutations; scenario
changes use authenticated simulator HTTP endpoints. Mixed states are normal
fulfillment, missing access, full refund, and failed payment. Extra notifications
are hints: a `succeeded` notification about a currently failed/refunded payment
must not override authoritative reads. The optional Docker restart is graceful;
the separate recovery demonstration supplies the actual process-death evidence.

The workload is 24 purchases across the two supported workspaces, not the original
10-workspace/5,000-purchase capacity target. Existing inventory remains background
load and is reported. The default timeout is 600 seconds after noisy traffic.
The first matching observation must begin after the explicit receipt arrives;
the metric can include time until an independent scheduled refresh. All missing
outcomes remain visible in counts. No revenue or user-time savings are measured.

### Reproduce a clean-checkout workload without deleting existing data

Use a new Compose project name for each fresh measurement. Each project owns a
separate PostgreSQL volume. Ports are the same loopback-only ports, so stop the
original stack during the isolated run and restore it in `finally`. The existing
`.env` supplies local credentials; never print or commit it. Both volumes are
preserved for inspection. A failed command throws rather than reporting a pass.

```powershell
$portfolioPreviousProject = $env:COMPOSE_PROJECT_NAME
$env:COMPOSE_PROJECT_NAME = 'payment-portfolio-' + (Get-Date -Format yyyyMMddHHmmss)
docker compose -p payment-operations-local stop
if ($LASTEXITCODE -ne 0) { throw 'Original stack did not stop' }
try {
    docker compose -f compose.yml -f compose.release.yml up -d --build --wait --wait-timeout 180
    if ($LASTEXITCODE -ne 0) { throw 'Isolated startup failed' }
    python scripts/benchmark_investigation.py --restart-worker
    if ($LASTEXITCODE -ne 0) { throw 'Benchmark did not pass' }
    python scripts/demo_recovery.py
    if ($LASTEXITCODE -ne 0) { throw 'Recovery demonstration did not pass' }
} finally {
    docker compose stop
    $env:COMPOSE_PROJECT_NAME = $portfolioPreviousProject
    docker compose -p payment-operations-local -f compose.yml -f compose.release.yml up -d --wait --wait-timeout 180
}
```

The default original name above comes from this repository's Compose file; use
your explicitly selected original name if you previously chose another one.
Fresh-project results describe that declared inventory only; they are not
evidence of a speedup over a differently populated historical database.

## Deliberately outstanding original requirements

Full account-managed Stripe acceptance, production identity/TLS/quotas, public
deployment, coordinated multi-system restore, broad accessibility review,
retention policy, the original large-inventory envelope, and customer validation
remain open. A finished local portfolio deliverable does not mark those passed.

The technical explanation and author's walkthrough questions are in
[ENGINEERING-CASE-STUDY.md](ENGINEERING-CASE-STUDY.md).
