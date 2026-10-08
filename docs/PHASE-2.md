# Phase 2: durable simulator ingestion and current evidence

Updated: 2026-10-08. User decision: finish the independent simulator path and
add account-managed Stripe credentials later. No temporary Stripe sandbox or
existing CLI profile is used. The initial simulator implementation passed
[hosted CI](https://github.com/void-devourer/ai-payment-operations-agent/actions/runs/37815328918)
on `4257a83`; current-commit results are available in
[Software checks](https://github.com/void-devourer/ai-payment-operations-agent/actions/workflows/ci.yml).

## Delivered workflow

1. The simulator commits an event alongside its payment/reversal change.
2. A separate simulator worker delivers raw JSON with a fresh timestamped HMAC.
3. `/webhooks/simulator/{destination}` resolves a server-configured workspace,
   checks raw bytes, a five-minute timestamp window, account/environment and shape.
4. A PostgreSQL transaction commits the authenticated receipt and a read job before
   HTTP 200. Failed transactions return HTTP 503. Duplicate event IDs preserve
   prior state; changed raw content with the same ID conflicts. Authentic unsupported
   versions are quarantined; unhandled valid types are recorded as ignored.
5. A separate console worker claims bounded jobs and retrieves current registered
   payment attempts, complete refund/dispute pages and authoritative target access.
6. Immutable observations retain independent completeness flags, request windows,
   source, API/normalizer versions and canonical SHA-256 content digest.

Webhook snapshots and metadata never create purchase bindings or authorize access.
This phase performs no target mutation. A payment read can be complete while
reversal reads are incomplete; financial completeness is explicitly false because
fees and settlement are not implemented.

## Recovery and bounds

Jobs use `queued`, `leased`, `retry_wait`, `completed`, and `dead` states. Claims
use short `FOR UPDATE SKIP LOCKED` transactions, 30-second leases and fresh lease
tokens. Each outbound read checks/refreshes ownership. Publication and completion
require a current unexpired token. Purchase generations and registered-attempt
checks reject superseded responses. Adding an attempt invalidates the previous
projection. New events during an active read increment a request sequence; a
successful old read queues another pass rather than losing that notification.

One sequential console worker serves one job per workspace per round. PostgreSQL
reserves a request slot per connection at most every 250 ms, shared across worker
processes. HTTP 429 also advances that connection's next slot using bounded
Retry-After guidance. This is a local initial budget, not a measured production
throughput guarantee or a distributed round-robin scheduler.

Each job is bounded by 20 seconds, 30 outbound requests, 20 registered attempts,
five pages per reversal collection, and 20 items per page. Responses and ingress
bodies are limited to 1 MiB. HTTP requests time out after five seconds. Permanent
permission/shape problems become dead jobs; transient network/5xx/429, missing
bindings and partial reads retry with bounded backoff/jitter, at most eight claims.
Exhausted crashed leases become dead as well. Work beyond the supported read
bounds stays incomplete; resumable broader scans belong to Phase 3.

The simulator delivery worker independently retains retries and dead delivery
states. It does not share the console's read-job table. Leased delivery completion
is fenced; receipt deduplication handles a lost acknowledgement.

## Inspection and simulator scenarios

Session-protected workspace endpoints expose paginated receipt/job summaries,
integration-health counts and latest current-generation observations. Raw event
bodies and service credentials are not returned. Operator/owner job redrive
requires CSRF and commits an audit record; it preserves the dead job ID. If newer
active work already exists for that resource, the unique constraint rejects redrive.

The simulator now supports separate attempts for one purchase, delayed/manual
capture states, canceled/failed states, synthetic refund/dispute history, paginated
reads, later-page failure, and controlled 403/429/503 read faults. These are explicit
development fixtures, not a model of every payment-network behavior. A reversal
generation detects changes between the payment read and reversal pages.

## Verification

Local result: 47 unit tests, 8 Phase 1 PostgreSQL/HTTP checks, 16 Phase 2 checks,
automatic webhook/evidence recovery, and the console-outage regression passed.
The existing PostgreSQL volume was upgraded through new `002` migrations without
editing an applied migration or deleting data. CI runs the same suites from a fresh checkout.

Commands:

```powershell
python -m unittest discover -s tests/unit -v
python scripts/check_phase1.py
python scripts/check_outage.py
python scripts/check_phase2.py
python scripts/check_docs.py
```

Phase 2's script temporarily pauses and restores the three workers. Tests use real
non-owner PostgreSQL transactions and actual service HTTP calls, plus a local ASGI
request for controlled HTTP commit failure. It checks duplicate/conflicting events,
quarantine, signature scope/recency and size limits; receipt/job rollback and 503;
current reads despite misleading snapshots; full/partial reversal pagination; RLS
and append-only observations; expired ownership and reclaim; notification during
read; denied reads, CSRF/audit/redrive; throttling; event-before-registration;
all-attempt coverage and manual capture; stale generations; concurrent claims;
binding mismatch; retry exhaustion; and a reversal arriving between reads. A final running-worker check verifies
automatic delivery and evidence collection after restart.

Hosted CI runs this suite after the existing Phase 1 and outage checks. Benchmarks,
in-flight process-kill chaos, provider history backfill, browser UI and production
identity remain later gates. Real Stripe signature/resource behavior is **unverified**
until a separately reported account-managed sandbox suite passes (F2-04).

## Provider references and boundary

The simulator's `simulator.v1` contract and `Simulator-Signature` header are deliberately
separate from Stripe. The adapter reads simulated resources only. The raw-byte
signature and current-resource design follows the principles in
[Stripe's signature guidance](https://docs.stripe.com/webhooks/signature) and
[Event version contract](https://docs.stripe.com/api/events/object).
Future Stripe reversal reads must follow its independent
[refund](https://docs.stripe.com/api/refunds/list) and
[dispute pagination](https://docs.stripe.com/api/disputes/list) contracts, including
relevant Charge coverage. Simulator tests do not establish that compatibility.
