# Local synthetic release package

This package runs on a developer machine. It does not provision a cloud account,
expose a public endpoint, connect to live payments, or supply production identity.
Use only generated synthetic customers. The reference product and simulator are
separate services with separate databases; restarting the console does not stop
ordinary fulfillment. No temporary Stripe sandbox is required.

## Start from a clean checkout

Install Docker Desktop, Python 3.13 or 3.14, and Git. Clone the repository, then:

```powershell
python -m pip install -r requirements.lock
python scripts/setup_local.py
docker compose -f compose.yml -f compose.release.yml up -d --build --wait --wait-timeout 180
python scripts/demo.py --scenario missing-access
```

Open the console at `http://127.0.0.1:8000`. The private local login key is in `.env`;
enter it in the sign-in form and select `owner_a`. Never paste it into a ticket,
chat, screenshot, recording or commit. The setup script refuses to overwrite an
existing environment. All published ports bind to loopback. Do not use a tunnel
or change port bindings to `0.0.0.0`: fixture identities, HTTP cookies and local
service credentials are unsuitable for public deployment.

The release override caps PostgreSQL at two CPUs / 512 MiB and each API/worker at
one CPU / 256 MiB. It removes application capabilities and prevents privilege
escalation. The load generator runs on the host and is not resource limited.
These limits are a reproducible test profile, not a sizing recommendation.

## Demonstrate the failure and recovery

1. Run the missing-access command above. Keep its printed purchase ID.
2. Wait for the real 120-second grace and the next successful evidence read.
   Refresh the console; find that purchase's `PAID_ACCESS_MISSING` case.
3. Inspect payment, reversals, access revision and evidence freshness. Preview
   the repair, review the exact purchase/customer/product/revision/expiry, enter a
   reason and approve. The script never approves or grants access itself.
4. Refresh until the operation shows a target receipt and fresh verification.
   Successful recovery means current access is active and the case is resolved.
5. Sign in as `viewer_a` to demonstrate investigation without mutation permission.

Other lab scenarios:

| Command / fault | Expected result | Clear / verify |
| --- | --- | --- |
| `python scripts/demo.py --scenario normal` | Independent ordinary fulfillment activates access | Inspect the reference access and console evidence |
| `python scripts/demo.py --scenario provider-outage` | Synthetic provider returns 503; evidence remains incomplete and no repair is eligible | Run `python scripts/demo.py --clear-fault SIMULATED_INTENT_ID`; wait for retry or redrive a dead job |
| Unsigned, conflicting or unsupported event | Rejected or durably quarantined, never trusted payment evidence | Ingestion integration suite |
| Refund, dispute, suspension, changed revision | Repair blocked or sent to review | Detection and repair integration suites |
| Process death after target commit | Same operation receipt lookup; no second dispatch | Repair integration suite's actual child-process crash |
| Missing target receipt | Outcome stays unknown | Repair integration suite; do not create another identity |

The advanced fault catalog is exercised by `check_phase2.py`, `check_phase3.py`
and `check_phase4.py`. These checks pause workers and sometimes use test-specific
administrator mutations. They are verification tools, separate from the
HTTP-only demonstration script. Run them sequentially, never during a load test.

## Backups, restore and remote outcome safety

```powershell
python scripts/restore_drill.py
```

The drill takes a consistent console `pg_dump` snapshot, writes its binary dump
under ignored `.local/restore-drill`, creates a **new** `release_drill_<uuid>`
database, restores into it, disables new repair execution and deletes restored
sessions **before any runtime services are started**. It verifies migration
checksums. It never overwrites a running database or starts scratch services.
Scratch databases remain for inspection; no automatic destructive cleanup runs.
Keep dumps private and delete them through your normal reviewed local cleanup.
They contain raw signed events, internal customer identifiers and audit reasons.

This is a console restore drill, not a coordinated three-system point-in-time
restore. Payment and target facts must be read from their surviving authoritative
systems. A snapshot taken before a dispatch marker can lose all knowledge of a
later remote effect. Receipt identity lost from that snapshot cannot be guessed.

For an actual incident: stop the old console API and worker, preserve the old
database and logs, restore to an isolated database, apply migrations, disable
`execution_control` as the database administrator, invalidate sessions, and
only then inspect through isolated read-only tooling. Never run two console
installations against the same target during restore. Look up known dispatched
operations using their existing identities. Do not replay a missing receipt as
a new grant. Reconcile authoritative payment/reversal/access state and compare
surviving audit/target receipts before authorizing any new repair.

The runtime role can read but cannot modify the execution switch. When disabled,
new approvals return 503, undispatched queue items are not claimed, and dispatch
rechecks the pause. Already dispatched receipt lookup/verification remains
possible. The switch cannot cancel a call already in flight: stop and drain the
worker **before** changing it. Enabling requires an administrator's reviewed
recovery procedure. A restored expired/revoked session never regains authority.

No automatic retention deletion is implemented. Audit decisions, operation
identities, receipts and attempts are append-only to application roles and remain
available for recovery. A future production retention policy must separate raw
event expiry from immutable operation recovery records and backup retention.
Default HTTP access logs are disabled because URLs and query strings can contain
submitted secrets. Validation errors return only fixed messages/error categories.
This does not sanitize arbitrary free-text audit reasons or existing backups;
operators must enter synthetic descriptions and keep the private dumps local.

## Health and incident procedure

- `/health/live` reports a running API process; `/health/ready` checks database
  connectivity. Provider availability is visible through job/evidence state.
- Integration health shows queued/retry/dead work and oldest creation times.
  Reconciliation coverage distinguishes scheduled reads from verified evidence.
- Do not infer recovery from a webhook, an HTTP timeout, a historical receipt, or
  a green process heartbeat. Inspect the latest authoritative access evidence.
- Redrive only after fixing the fault. Recovery uses the original operation ID.
  Repeated automatic attempts are bounded; no direct SQL grant is a repair path.
- Preserve volumes. `docker compose stop` pauses services; `docker compose start`
  starts them. Do not use `down -v` or replace `.env` for incident recovery.

## Verification and benchmark

```powershell
python -m unittest discover -s tests/unit
python scripts/check_docs.py
python scripts/check_phase5.py
python scripts/benchmark_release.py --rate 25 --seconds 600
python scripts/benchmark_release.py --rate 100 --seconds 30
```

The benchmark sends unique signed notifications about two actual simulated
purchases across two fixed workspaces, with a 90/10 traffic split. It measures
acknowledgment latency, dropped load-generator slots, response status, durable
receipt counts, per-workspace latency and an end-of-run queue-age snapshot.
Per-request timings and summary JSON stay under `.local/benchmarks`.
Do not equate ingress fairness with dispatch fairness, or this hot-key workload
with the planned 10-workspace / 5,000-purchase / 20,000-event inventory benchmark.
That broader workload requires configurable identities and additional measurement.

## Capability and remaining gates

| Capability | Local package |
| --- | --- |
| Simulator payment, signed delivery, independent reference app | Implemented |
| Current evidence, detection, reconciliation, operator preview/approval | Implemented and integration tested |
| One conditional access grant and same-identity recovery | Implemented and integration tested |
| Isolated console restore with execution paused | Automated drill |
| Public hosting, TLS, production OIDC, distributed quotas | Not provided |
| Account-managed Stripe payment/refund/dispute acceptance | Pending account access |
| Live charges/refunds/payouts, automatic money movement | Unsupported |
| Subscription/proration/tax/financial ledger | Unsupported in this software phase |
| Generative AI investigation assistant | Next phase after its own design/evaluation gate |
| Real customer need / supervised pilot | Pending user discovery |

Public deployment needs a separate identity/secrets/TLS design and a selected
hosting target. This local package does not declare all P0 release requirements
passed. See [PHASE-5.md](PHASE-5.md) for measured evidence and outstanding gates.
