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

Measured results are recorded after running the sustained and burst commands in
the [release runbook](RELEASE-RUNBOOK.md). Raw outputs remain in ignored local
artifacts; the workload and measured summary will be reported here.

## Remaining release gates

- The intended 10-workspace / 5,000-purchase / 20,000-mixed-event inventory and
  dispatch-fairness benchmark is not implemented. The current fixed two-workspace
  hot-key ingress workload cannot establish that capacity.
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
