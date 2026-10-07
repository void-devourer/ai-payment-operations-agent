# Payment Reliability & Reconciliation Console

Software project for investigating successful payments that did
not produce the expected access in a business application, with controlled,
human-approved repair and verified recovery.

The primary career focus is software engineering. A read-only, evaluated AI
investigation assistant is a later extension. Data Reliability & Replay is a
separate project and is not implemented in this workspace.

## Read in this order

1. [Project direction](PROJECT-DIRECTION.md): current decisions and project split.
2. [Build plan](PLAN.md): scope, product workflow, stack, phases, release gates.
3. [Domain glossary](CONTEXT.md): precise vocabulary.
4. [Architecture](docs/ARCHITECTURE.md): data, APIs, state, concurrency, recovery.
5. [Acceptance plan](docs/ACCEPTANCE.md): requirements and verification scenarios.
6. [Stripe research](docs/RESEARCH.md): primary sources and provider limitations.

## Current status

Phase 0 has an executable deterministic policy, 31 passing unit tests, exact
integration contracts, a discovery guide, an owned backlog, and CI configuration.
See the [phase report](docs/PHASE-0.md) for evidence and setup gaps. The application,
database/target integration, genuine Stripe adapter, AI assistant, deployment and
benchmarks are not built yet. The user need still requires validation.

Run the Phase 0 checks with Python 3.13 or 3.14 from the repository root:

```powershell
python -m unittest discover -s tests/unit -v
python scripts/check_docs.py
```

Next: Phase 1 foundation, tenant isolation, reference business application, and
simulator. The later vertical slice registers a purchase, observes a successful
payment, detects missing access, and verifies a human-approved conditional repair.

Local historical brainstorming and generated credentials/tools are ignored by
Git. Use the planning documents above for the current scope. This repository is
being built and verified one phase at a time.
