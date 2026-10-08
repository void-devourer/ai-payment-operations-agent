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

Phase 0 established the policy and contracts. Phase 1 now has console, reference
business app and simulator APIs, PostgreSQL migrations/RLS, sessions, a durable
registration outbox, and conditional access/receipts. **40 unit tests and 8 real
PostgreSQL/HTTP tests pass**, together with console-outage recovery.
[Hosted CI passed](https://github.com/void-devourer/ai-payment-operations-agent/actions/runs/37810505482).
See [Phase 1](docs/PHASE-1.md) and the
[local setup guide](docs/LOCAL-DEVELOPMENT.md). Genuine Stripe integration, the
frontend, AI, deployment and benchmarks remain later work; user need is unvalidated.

Run local unit checks with Python 3.13 or 3.14 and the pinned dependencies:

```powershell
python -m pip install -r requirements.lock
python -m unittest discover -s tests/unit -v
python scripts/check_docs.py
```

Phase 1's foundation gate is complete. Phase 2 adds durable signed simulator
webhooks, leased read jobs, current payment/reversal/access observations and
inspection/redrive APIs. See [Phase 2](docs/PHASE-2.md) and the
[current hosted checks](https://github.com/void-devourer/ai-payment-operations-agent/actions/workflows/ci.yml).
Local verification now passes 47 unit tests, 8 Phase 1 and 16 Phase 2 integration
checks, plus automatic webhook/evidence recovery and the console-outage check.
The optional Stripe adapter and genuine test runner are now implemented; see
[Stripe setup](docs/STRIPE-SETUP.md). Genuine verification remains blocked on
account creation and credentials. Offline Stripe fixtures do not close that gate. The later
vertical slice detects missing access and verifies a human-approved repair.

Local historical brainstorming and generated credentials/tools are ignored by
Git. Use the planning documents above for the current scope. This repository is
being built and verified one phase at a time.
