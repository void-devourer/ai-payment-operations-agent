# Phase 1 foundation and reference application

Updated: 2026-10-08. The local Phase 1 foundation gate passes, including real
PostgreSQL/HTTP and console-outage checks. Hosted CI result remains to be confirmed.

## Implemented foundation

- Three FastAPI services with separate PostgreSQL databases and runtime roles.
- Strict purchase, attempt, checkout and target grant request contracts.
- Immutable registration, exact attempt binding and idempotent checkout.
- Opaque server sessions, membership/role guards, CSRF-protected logout and
  development-only fixture identities; production mode is rejected.
- Transaction-local workspace/subject context, forced row-level security,
  runtime role privilege checks, and append-only operation receipts.
- Reference application's ordinary fulfillment, versioned access, conditional
  grants and stable payload-bound operation receipts, including failure tombstones.
- Durable reference registration outbox with fenced leases, retry and visible
  dead state; purchase registration precedes attempt registration.
- Independent persistent payment simulator with completion, signed event fixtures,
  and a deliberate normal-fulfillment pause.
- Generated ignored secrets, pinned runtime dependencies, transactional migration
  jobs, Compose startup dependencies, and real-PostgreSQL CI configuration.

## Decisions and verification

The initial stack choices were proposals. This implementation uses psycopg2 and
versioned SQL migrations so transaction/RLS/receipt behavior is explicit without
an additional ORM layer. Existing standard-library tests continue, alongside
real database/HTTP acceptance scripts. Production OIDC remains a separate verified
integration; no development identity shortcut can start in production mode.

Observed so far: **40 local unit tests pass**, all three APIs generate their
OpenAPI contracts, Compose configuration validates, and all acceptance IDs remain
mapped. Runtime dependencies are pinned to the compatible installed closure and
are also installed from scratch by the container build.

Observed on the local Compose stack: fresh migrations succeeded, all three APIs
became ready, and **8 real PostgreSQL/HTTP integration tests passed**. These verify
concurrent/replayed grants, changed payload/precondition rejection, atomic
access/receipt rollback under an injected write failure, real RLS/pool isolation,
cross-database connection denial, immutable registration/attempt binding,
session/CSRF behavior, synthetic event signing, and ordinary fulfillment yielding
a `healthy` policy decision.

The separate console-outage check also passed: normal reference fulfillment
activated access with revision 1 while the console was stopped; after restart,
both durable purchase and attempt registrations reached `sent`. This does not
prove universal recovery or the later console executor's unknown-outcome behavior.

Environment: Windows host Python 3.14.2, Python 3.13 application containers and
PostgreSQL 17. Host port 55432 was reserved/denied by Windows; using configurable
port 15432 resolved startup without deleting data. The pinned dependencies
installed in a fresh image; the host dependency consistency check also passed.
The CI workflow runs the same database/HTTP/outage commands after push; hosted
success is not claimed until its result is confirmed.

## Scope boundaries

These services implement local API workflows. The operator frontend, durable
console webhook inbox/jobs, current Stripe evidence, cases/reconciliation,
console approvals/executor, production identity, AI and financial reconciliation
retain their later phase gates. The simulator currently provides completion and
fulfillment pause; later refund/dispute/network scenarios are not yet implemented.

See [LOCAL-DEVELOPMENT.md](LOCAL-DEVELOPMENT.md) for exact commands and limitations.
