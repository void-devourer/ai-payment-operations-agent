# Investigation workload profiling and scheduling correction

Completed locally 2026-10-11. Both controlled workload reports and correctness
checks are retained below.
This phase changes read scheduling, not policy, access repair or the operator UI.

## Baseline and reproduction

The actual 90-second historical-worker profile is retained in
[historical-profile-before.json](benchmarks/performance/historical-profile-before.json).
It ran inside the release-profile container, replacing the normal console worker
temporarily and restoring it in `finally`. It used the real source services,
runtime database role and production worker loop. Diagnostic wrappers recorded
transaction, source-read, scheduling and job wait timing without credentials or
payload logging. No administrator mutations or request-budget changes occurred.

The profile serviced 99 jobs (50 A / 49 B). Source-read calls consumed 75.37
seconds, streamed HTTP calls 2.20 seconds, database transactions 7.45 seconds,
and sweep scheduling 0.18 seconds. `time.sleep` consumed 80.23 seconds, including
loop pacing and waits for the connection budget. Metrics overlap; adding these
durations is invalid. The profile identifies budget waiting as a dominant cost,
not a CPU-heavy algorithm or slow source endpoint. It does not establish that
every workload has the same bottleneck.

Ranked hypotheses: sequential budget waits hold up the other workspace; FIFO
queues put fresh evidence requests behind independent sweep work; sweep
coalescing causes unnecessary re-reads or premature timer wakeups. Fast
regressions reproduce each mechanism: blocked workspace A prevented B from
entering a read; an older sweep job preceded a new hint; a sweep incremented the
claimed request sequence and shortened a queued grace timer. These failed
before correction. The queue tests use separate test-only workspace scopes and
controlled timer fixtures, not production clock changes.

## Correction

- A single worker container runs one bounded loop per configured workspace (two
  threads), each with its own HTTP client and scan pacing. It keeps the threaded
  database pool and existing per-connection request limits. A loop failure fails
  the process; health checks require both workspace heartbeats.
- Migration 007 adds a durable foreground/background label. Existing jobs remain
  background. Explicit hints and registrations promote foreground work; grace
  follow-ups become foreground when their observation publishes.
- Four turns prefer foreground jobs; the fifth prefers background jobs. If the
  preferred class has no eligible work, the same claim falls back to the other
  class. Due times, lease ownership/expiry, retry backoff and attempt limits are
  still checked. This is a claim-count policy, not a wall-clock fairness SLA.
  A process restart resets the local five-turn counter.
- Sweep scheduling coalesces with active jobs without marking a leased read
  dirty, shortening its grace timer, or resetting retry backoff. Authenticated
  hints still dirty a concurrent read so updated facts receive a follow-up.

No provider budget was increased; no money movement, eligibility shortcut,
automatic approval, target-identity replacement or receipt change is included.

## Workload comparison methodology

Before and after use separate new Compose projects and the same resource limits:
one console worker container (1 CPU / 256 MiB), two supported workspaces, 320 A
and 32 B synthetic background purchases, then 12 new purchases per workspace,
300 extra A notifications over 30 seconds, a graceful worker restart, and the
same 600-second post-noise timeout. Background purchases use normal fulfillment;
the 24 measured purchases include normal, missing-access, refunded and failed
states. The benchmark never approves a repair. Real grace and lease clocks stay
unchanged. Original volumes are preserved and the original stack is restored.

The fixture helper creates background purchases through HTTP with console-worker
stopped, then waits for every payment attempt to be registered and every native
notification to arrive. It explicitly marks only their queued read jobs as
background through the runtime role, modelling an accumulated sweep backlog.
This is a declared test-fixture scheduling mutation, not an administrator change
to payment/access facts or success clocks. Both controlled runs use the same
schema, HTTP services and fixture labels; the old cached worker ignores the new
priority label and places all these queued jobs in its FIFO queue. Subsequent
actual notifications can still promote a background fixture. IDs and exact native
delivery timing vary; the comparison is not a statistically matched trial or a
replay of the historical dataset's injected faults. The older historical failed
result remains valid and is not replaced by this constructed workload.

Fixture preparation drains eligible registration messages through the existing
reference-worker relay, retaining its leases, acknowledgements and backoff but
omitting the one-second inter-round sleep during setup. The baseline needed this
drain invoked separately; the optimized run invokes it within the helper. Both
measurements start only after the same 320/32 registration-and-notification
barrier. During measurement the normal reference worker and its pacing are
unchanged. The helper rejects an existing registered inventory.

The cached baseline worker image is
`sha256:b74a5fb7fedbd75608594547aadb1d4ff47488e435822bdf0ec37f6d1349e29f`;
the optimized worker image is
`sha256:933b5c99db28e2a45a5e8a2755c03e561340dc17d3c8aab8629f19d2748fc505`.
Both use migration 007 and the same source/API images. The baseline retains its
original single-heartbeat health check; the optimized worker checks both loops.
The 4:1 preference is an initial explicit scheduling policy, not an empirically
optimal ratio.
The measured treatment combines the three independently reproduced scheduling
corrections. It establishes their combined effect; it does not attribute a
percentage of the improvement to each correction. That would require separate
ablation runs.

An initial run lacked the readiness barrier:
[setup-race-run.json](benchmarks/performance/setup-race-run.json). It seeded 352
checkouts but had only 27 A and 6 B registered purchases at measurement start.
It observed 14/24 outcomes before its declared deadline. This revealed the
asynchronous registration setup error, so it is retained but excluded from the
controlled speed comparison. The fixed helper refuses to start measurement
until all requested background registrations and native hints are present.

Measure each workspace's receipt-to-complete-evidence latency and expected-policy
decision latency, report post-grace detection separately, preserve missing
outcomes, and count durable receipts, skipped load slots, unauthorized repairs
and background jobs remaining at completion. Faster new-case processing does
not mean the entire inventory can be refreshed every 60 seconds.

## Results and limits

Raw reports: [workload-before.json](benchmarks/performance/workload-before.json)
and [workload-after.json](benchmarks/performance/workload-after.json).

| Measurement | Before | After |
| --- | --- | --- |
| Expected outcomes A / B | 9/12 / 12/12 | 12/12 / 12/12 |
| Complete-evidence p95 A (12/12 measured in each run) | 627.82 s | 44.18 s |
| Complete-evidence p95 B (12/12 measured in each run) | 81.80 s | 28.58 s |
| Expected-decision p95 A | 627.82 s, 9/12 measured; 3 missing | 159.52 s, 12/12 measured |
| Expected-decision p95 B | 251.16 s, 12/12 measured | 144.80 s, 12/12 measured |
| Missing-access detection after grace A | 0/3 measured; all missing | 2.24 s p95, 3/3 measured |
| Missing-access detection after grace B | 53.94 s p95, 3/3 measured | 2.90 s p95, 3/3 measured |
| Notification receipts / skipped slots | 324/324 / 0 | 324/324 / 0 |
| Webhook acknowledgement p95 | 8.29 ms | 8.89 ms |
| Automatic repair operations | 0 | 0 |
| Active jobs at measurement end A / B, including background | 3 / 16 | 292 / 8 |

Complete-evidence p95 was about 14.2 times lower in A and 2.9 times lower in B
in these runs. Each complete-evidence sample includes all 12 measured purchases.
Do not compare A's partial before-decision percentile as if it included the three
missing outcomes. Decision timing includes the unchanged real grace period for
missing access. The benchmark stops at success or the same declared deadline:
the optimized run stopped earlier, with much more background inventory still
queued. End queue counts therefore are not equal-duration throughput comparisons
or a proof of background completion. The separate scheduling regression proves
the background-preferred claim receives an eligible background job.

The baseline missed all three A missing-access decisions; the optimized run
reached all 24 expected decisions within the deadline. This establishes improved
fresh-case service in this synthetic two-workspace backlog, not a global freshness
SLA, arbitrary-workspace isolation, a production capacity guarantee, or successful
replay of the historical fault dataset. Provider budgets still bound total work.

Verification: 85 unit tests; 16 Phase 2, 12 Phase 3, 3 scheduling, 14 Phase 4,
and 8 Phase 5 PostgreSQL/HTTP scenarios (53 total). Phase 4 includes actual
process-death recovery; Phase 5 verifies previous-schema upgrade and isolated
restore. The blocked-workspace unit test failed before the loop correction and
passes afterward. Three queue regressions passed after previously reproducing
foreground starvation, sweep dirtying and premature timer wakeup. Documentation
links, requirement coverage, helper compilation and whitespace checks passed.
The original stack and preserved volume were restored with all services healthy.

## Reproduction

Use the isolated-project procedure in [PORTFOLIO-FINISH.md](PORTFOLIO-FINISH.md),
with a fresh project name for each run. Before the benchmark:

For a baseline reproduction, build the worker from commit `a002416` in a
separate checkout, tag that worker image, and override only `console-worker` in
the current Compose configuration. Keep the current migration/source services
and release resource limits. Override its health check with the historical
single `/tmp/console-worker-heartbeat` check; the current check expects two
markers that the old worker does not create. The recorded image IDs identify
this run's local builds; independently rebuilt images can have different IDs.
The optimized run uses the current worker and current health check. These
experiments occupy the same local ports, so stop the original stack first and
restore it afterward without removing its volume.

```powershell
docker compose stop console-worker
python scripts/seed_profile_inventory.py --a 320 --b 32
docker compose start console-worker
python scripts/benchmark_investigation.py --restart-worker
```

Do not run fault suites or the crash demonstration during a measured workload.
Focused checks: `python scripts/check_scheduling.py` and
`python -m unittest discover -s tests/unit -p test_worker_isolation.py`.
Database scheduling fixtures use isolated test-only workspace scopes.
