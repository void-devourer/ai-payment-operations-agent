# Phase 5 — local release hardening

Local package implementation: 2026-10-09. Public hosting was explicitly deferred
in favor of a local demo/deployment package. The full release gate remains open;
the checks below are evidence for specific implemented safeguards.

## Implemented

- Validation failures omit submitted values, field names and exception contexts
  on all three services. Console responses prevent framing and content sniffing;
  the built frontend has a same-origin content security policy. Raw HTTP access
  logging is disabled to avoid exposing URL/query values.
- An administrator-owned execution switch prevents new approvals/dispatches
  during recovery. Runtime roles cannot change it. Previously dispatched receipt
  lookup and verification can continue with the same operation identity.
- Migration 006 adds that switch without modifying prior migration checksums.
- The isolated console dump/restore drill preserves queued operations and approval
  identities, pauses execution and invalidates restored sessions before starting
  any services. Previous-schema upgrade and checksum rejection are tested.
- HTTP-only demo commands create normal fulfillment, missing access and provider
  outage scenarios. The real grace period and operator review still apply.
- A resource-limited Compose override packages the synthetic local deployment.
  A bounded signed-ingress benchmark records per-request timings and summaries.
- Hosted CI includes the release security/restore suite after earlier regressions.

## Verification evidence

79 unit contracts passed. Eight additional PostgreSQL/HTTP release scenarios
passed with the resource-limited profile:

1. All scoped read endpoints deny anonymous and other-workspace identities;
   viewers retain permitted investigation reads.
2. Pausing prevents approval, queue claim and even manually leased first dispatch
   without deleting pending work or changing target access.
3. Runtime cannot update/delete the switch, decisions, attempts or audit rows.
4. A consistent console backup restores pending operation/proposal identity into
   a separate database, with execution disabled and sessions invalidated.
5. Previous schema upgrades once; rerun is idempotent; altered checksum fails.
6. All operator mutations deny anonymous, viewer, other-tenant and missing-CSRF
   requests using syntactically valid payloads.
7. A known dispatched grant recovers through its original target receipt while
   new execution is paused, preserving access revision 1.
8. Secret canaries in invalid bodies and URL query strings do not appear in
   validation responses or captured service logs.

The changed repair path also passed all fourteen earlier repair scenarios,
including actual process death after target commit. The migration/restore checks
retain isolated scratch databases and ignored local dumps for inspection.
No running database or persistent volume was replaced.

## Benchmark record

Measured on Windows 11, AMD Ryzen 7 7435HS (8 cores / 16 logical CPUs),
25,439,199,232 bytes physical RAM. Docker Desktop engine 29.8.2 had 16 CPUs and
12,377,022,464 bytes available; the release override limited PostgreSQL to two
CPUs / 512 MiB and each API/worker to one CPU / 256 MiB. PostgreSQL was 17.11;
the host load client used Python 3.14.2, concurrency 16, localhost HTTP and a
90% A / 10% B traffic split. One instance of each worker ran throughout.

The preserved local database already contained 259 workspace-A and 15 workspace-B
purchases, plus four isolated test-registration fixtures. Each benchmark adds
two purchases; it sends unique notifications repeatedly about those purchases.
Historical controlled-fault jobs and periodic reconciliation remained enabled.
The two tests ran sequentially without pausing/restarting services during load.

| Measurement | Sustained | Burst |
| --- | --- | --- |
| Requested load | 25 requests/sec for 600 sec | 100 requests/sec for 30 sec |
| Sent / HTTP 200 / durable receipts | 15,000 / 15,000 / 15,000 | 3,000 / 3,000 / 3,000 |
| Skipped load-generator slots | 0 | 0 |
| Elapsed time | 599.98 sec | 30.03 sec |
| p50 / p95 / p99 acknowledgment | 10.16 / 22.56 / 24.69 ms | 6.69 / 8.67 / 19.05 ms |
| Workspace A / B p95 | 22.55 / 22.63 ms | 8.67 / 8.69 ms |
| Oldest active job creation age A / B at end | 599.97 / 599.99 sec | 42.07 / 30.01 sec |

The proposed ingress p95 <300 ms target passed for this workload. A coalesced
job retains its original creation time while repeated requests keep it active;
the age snapshot is **not** the wait for its most recent trigger or a dispatch
fairness proof. A later post-load check found current published evidence heads
for all four benchmark purchases, but maximum latest-observation age was 99.51
seconds for workspace A and 41.70 seconds for B. This does **not** establish
60-second freshness across the populated workspace. Rate budgets, backlog,
tenant inventory size and worker scheduling need a separate end-to-end benchmark.

Tracked exact summaries: [sustained](benchmarks/sustained-25-rps.json) and
[burst](benchmarks/burst-100-rps.json). Per-request timing arrays stay in
`.local/benchmarks`. Commands and limitations are in the
[release runbook](RELEASE-RUNBOOK.md).
After both runs, the console worker was restarted. All 18,000 benchmark receipts
remained stored (15,000 sustained / 3,000 burst), and every long-running service
returned healthy. This verifies receipt retention across worker restart, not a
database crash or a time-bounded recovery SLA.

The implementation commit's [hosted CI run](https://github.com/void-devourer/ai-payment-operations-agent/actions/runs/37966686519)
passed all policy, prior integration and release checks. Browser verification
confirmed the built console/Integration health page renders with the CSP and no
browser error/warning logs; the frontend type check/build passed locally.

## Remaining release gates

- The intended 10-workspace / 5,000-purchase / 20,000-mixed-event inventory and
  dispatch-fairness benchmark is not implemented. The current fixed two-workspace
  hot-key ingress workload cannot establish that capacity.
- A 60-second evidence-freshness or abandoned-lease recovery bound is not proved
  by the ingress timing results. Controlled crash recovery is separately tested.
- Broader accessibility audit, production identity/TLS/quotas, coordinated restore
  evidence and an operational retention/export policy remain separate work.
- Arbitrary free-text audit reasons and raw event backups are not automatically
  scrubbed for personal information. The local package uses synthetic inputs.
- Genuine account-managed Stripe account/dispute acceptance and real user pilot
  evidence remain open. No live provider writes are supported.
- This package has not passed a production vulnerability review or proved public
  hosting safety. Container builds pin application dependencies but base image
  tags still move; capture image digests for an external deployment.

Generative AI stays deferred until the software scope's remaining gates are
explicitly resolved or narrowed, followed by its own read-only design/evaluation.
The package and recovery instructions are in [RELEASE-RUNBOOK.md](RELEASE-RUNBOOK.md).
