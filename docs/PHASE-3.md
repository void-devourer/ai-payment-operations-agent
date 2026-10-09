# Phase 3: detection, reconciliation and case investigation

Implemented 2026-10-09 on the independent simulator path. Phase 3 does not grant
access, create approval proposals, execute refunds or use AI. Those keep their
later gates. Full account-managed Stripe acceptance remains open; the genuine
temporary smoke result and its permission limits are in [STRIPE-SETUP.md](STRIPE-SETUP.md).

## Durable detection

Every lease-fenced observation publication now commits its policy evaluation and
case projection in the same PostgreSQL transaction. A purchase-head lock serializes
competing observations; stale generation/lease/attempt sets cannot publish a case.
The policy is `one_time_access_v1`, with a 120-second fulfillment grace period and
60-second freshness bound measured from the oldest read in each required bundle.
Payment, reversal and access completeness are independent of financial settlement.

The first authoritative succeeded payment read is persisted once per registered
attempt, using its payment-window completion time. Webhook creation time and an
old event payload cannot start or backdate that clock. Runtime roles cannot update
the clock or evaluation history. Policy input uses trusted purchase/connection
bindings and every registered attempt; malformed, partial, stale or contradictory
facts produce uncertainty rather than a grant candidate.

One active case per purchase/discrepancy is enforced by a partial unique index.
Cases preserve generations, first/latest observations, policy outcome/reasons and
material fingerprints. Read timestamps, transport errors and simulator reversal
generation counters do not create new dismissal generations. Payment state/value,
attempt sets, reversal resources/statuses and access state/revision do.

An operator dismissal requires membership, write role, CSRF, a meaningful reason,
the exact observation/fingerprint and fresh current evidence. It appends an audit
record and suppresses unchanged findings. Material changes permit a new generation.
Head -> case lock ordering matches publication and avoids lock-order deadlocks.

`PAID_ACCESS_MISSING` resolves only after fresh complete policy facts establish
active business access; a successful read job alone cannot resolve it. Historical
refunds/disputes or multiple successes create separate manual-review findings.
Active access never silently resolves a reversal review; an operator must record
a disposition. Suspension/revocation remains blocked, without an automatic grant.

## Independent bounded reconciliation

The worker schedules at most 20 registered purchases per connection/page and one
page per workspace round, using a persisted run cutoff and purchase-ID cursor.
Each page's job enqueues and checkpoint commit atomically. Restarting resumes the
cursor; rows registered after the cutoff enter the next sweep. A completed sweep
starts again after a nominal 60-second pause. Every purchase is revisited regardless
of age or delivered events, including delayed payments and old purchases with new
refunds/disputes. One scheduled job reads all bounded registered attempts.

Scan state `scheduled` means work was queued, not that API reads succeeded. Coverage
reports registered, unobserved, incomplete and stale purchases (overlapping counts),
as well as unbound/over-budget purchases, dead/retrying jobs and quarantined events.
Read requests retain Phase 2 time/request/page/rate/lease limits. Queue pressure can
delay freshness beyond the nominal scheduling interval; the UI displays uncertainty.

**Scope limit:** this sweeps trusted registered purchases. Unregistered provider
inventory discovery and expired-event-history reconstruction are unsupported and
explicitly reported. It is not a claim of complete merchant-history coverage. Genuine
Stripe reads still require an account-managed sandbox with all required permissions.

## Operator console

The React 19.3.0 / TypeScript 7.0.2 / Vite 8.3.4 frontend has pinned dependencies and
a lockfile. Docker builds it and the console serves it at **http://127.0.0.1:8000**,
sharing an origin with its APIs and HttpOnly/SameSite session cookie. There are no
provider credentials in the frontend. API/identity responses use `Cache-Control:
no-store`; CSRF tokens stay in memory. A restored browser session can read, and must
sign in again for an action token. This remains a development identity fixture.

The console shows paginated cases, current facts, required-read completeness,
evidence source/version/digest, generation history (including pre-policy observations),
scan/job/receipt health and audited dispositions. Stale/superseded evidence is explicit.
Freshness expires in the browser using the server's oldest-read deadline; stale
actions are disabled and server checks independently reject changed evidence.
Labels, semantic buttons/forms, skip link, visible focus, detail focus transfer,
loading/empty/error states and responsive layout are implemented.

Routes added:

- `GET /api/workspaces/{workspace}/cases` (50-row keyset pages)
- `GET /api/workspaces/{workspace}/cases/{case_id}`
- `POST /api/workspaces/{workspace}/cases/{case_id}/dismiss`
- `GET /api/workspaces/{workspace}/purchases/{purchase_id}/timeline`
- `GET /api/workspaces/{workspace}/reconciliation`

## Verification and remaining gates

Local checks: 72 unit contracts and 10 real PostgreSQL/HTTP Phase 3 scenarios passed.
The Phase 3 suite covers durable grace clocks, deduplication, dropped and acknowledged
unprocessed events, an independently fixed target, reversal review on active access,
same-fingerprint suppression/new generations, viewer/cross-workspace/CSRF/conflict
denials, delayed payments, suspension, incomplete reads, transactional scan rollback,
concurrent fenced observations, old purchases, private responses and timeline pages.
Its controlled-clock fixtures use an administrative test connection to change only
their own synthetic clocks/target states; the product exposes no such endpoint.
Workers are paused for these fault fixtures and restored in `finally`.

The frontend type check and production build passed. An in-app browser walkthrough
verified login, real case/coverage/detail/timeline rendering, changed-evidence error,
viewer dismissal disabled, and keyboard focus moving from detail to its disclosure.
Broader screen-reader/accessibility, release security, chaos, migration-from-previous
schema and benchmarks remain Phase 5. Full approval/recovery remains Phase 4.

Regression checks passed: 8 Phase 1 PostgreSQL/HTTP contracts, all 16 Phase 2
contracts plus automatic background delivery, and 4 offline Stripe/PostgreSQL
contracts. Hosted CI includes the new Phase 3 suite and builds/type-checks the
frontend inside the application image; it never receives private Stripe secrets.

Reproduce after normal local setup:

```powershell
docker compose up -d --build --wait --wait-timeout 180
python -m unittest discover -s tests/unit
python scripts/check_phase3.py
```

For frontend development separately:

```powershell
cd frontend
npm ci --ignore-scripts
npm run dev
```

Vite's loopback dev proxy forwards the API and local login routes. Sign in using
the private generated `DEMO_LOGIN_KEY` from `.env` and a fixture identity. No Stripe
account or temporary sandbox is needed for this console or the simulator checks.
