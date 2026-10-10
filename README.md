# Payment Reliability & Reconciliation Console

Software project for investigating successful payments that did
not produce the expected access in a business application, with controlled,
human-approved repair and verified recovery.

The primary career focus is software engineering. A read-only, evaluated AI
investigation assistant is an optional future extension. The current deliverable
is a reproducible local reliability demonstration, with a bounded finishing
scope accepted on October 10. Data Reliability & Replay / TraceBack is a separate
candidate and is not implemented in this workspace.

## Try the local demo

Follow [the setup and release runbook](docs/RELEASE-RUNBOOK.md). The simulator
uses persistent independent services and needs no Stripe account. The ordinary
business application fulfills successful purchases itself; the console handles
exceptions through investigation and approved application-access repair.

```powershell
python scripts/demo.py --scenario missing-access
```

Open **http://127.0.0.1:8000** and review the generated case after its real grace
period. Credentials stay in the ignored local `.env` file.

## Engineering walkthrough

- [Case study](docs/ENGINEERING-CASE-STUDY.md): the post-commit failure window,
  tradeoffs, recovery sequence, and questions the author should understand.
- [Finishing evidence](docs/PORTFOLIO-FINISH.md): recorded crash demonstration,
  distinct-purchase investigation benchmark, and limitations.
- [Architecture](docs/ARCHITECTURE.md): database, worker, access adapter and API
  contracts; [domain vocabulary](CONTEXT.md) keeps payment and access distinct.

The crash demonstration's test harness approves only its own synthetic fixture.
Run it separately from the benchmark and integration suites:

```powershell
python scripts/demo_recovery.py
python scripts/benchmark_investigation.py --restart-worker
```

## Read in this order

1. [Project direction](PROJECT-DIRECTION.md): current decisions and project split.
2. [Build plan](PLAN.md): scope, product workflow, stack, phases, release gates.
3. [Domain glossary](CONTEXT.md): precise vocabulary.
4. [Architecture](docs/ARCHITECTURE.md): data, APIs, state, concurrency, recovery.
5. [Acceptance plan](docs/ACCEPTANCE.md): requirements and verification scenarios.
6. [Stripe research](docs/RESEARCH.md): primary sources and provider limitations.

## Current status

Phases 0–3 established the deterministic policy, independent reference business
application and payment simulator, PostgreSQL isolation, durable ingestion and
bounded evidence reads, all-age registered-purchase reconciliation, and the React
investigation console at **http://127.0.0.1:8000**.

Phase 4 adds exact repair previews, human approval/rejection, transactional repair
enqueue, conditional access changes, receipt lookup after uncertainty, and verified
business recovery. The Phase 4 verification record reports 77 unit contracts and all 14 PostgreSQL/HTTP
scenarios, earlier-phase regressions, the frontend build and the browser approval
walkthrough. See [Phase 4](docs/PHASE-4.md).
The console keeps its classic layout with separate Cases and Integration health
pages. Owner/operator actions require a fresh session and current evidence.

Run the local checks after the [setup guide](docs/LOCAL-DEVELOPMENT.md):

```powershell
python -m unittest discover -s tests/unit -v
python scripts/check_docs.py
python scripts/check_phase4.py
```

Implementation records: [Phase 1](docs/PHASE-1.md), [Phase 2](docs/PHASE-2.md),
[Phase 3](docs/PHASE-3.md), and [current hosted checks](https://github.com/void-devourer/ai-payment-operations-agent/actions/workflows/ci.yml).

The simulator needs no Stripe credentials and survives temporary sandbox expiry.
An isolated genuine temporary-sandbox smoke test passed on October 9 for payments,
refunds, manual capture and signed webhooks. Full account-managed Stripe acceptance
remains open because the temporary key denies account and dispute reads. See
[Stripe setup](docs/STRIPE-SETUP.md). Offline fixtures and that limited smoke result
do not close the genuine-provider gate.

Phase 5 adds safe validation/logging, a recovery execution pause, isolated backup
restore checks, and a reproducible resource-limited local demo. See the
[release runbook](docs/RELEASE-RUNBOOK.md) and [verification record](docs/PHASE-5.md).
The broader release gate remains open. AI is a later read-only evaluated extension. User need is unvalidated;
local fixture identities are not production authentication.

The October 10 finishing pass adds a recorded process-death demonstration,
distinct-purchase investigation measurements, and an engineering case study.
It found and corrected delayed grace-boundary refreshes and stale resolved-case
evidence during recovery. Current unit coverage is 83 contracts. The finishing
record preserves both successful local measurements and failed workload/crash
traces, with the regression checks and remaining limits.

Local historical brainstorming and generated credentials/tools are ignored by
Git. Use the planning documents above for the current scope. This repository is
being built and verified one phase at a time.
