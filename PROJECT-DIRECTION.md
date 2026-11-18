# Current project direction

Updated: 2026-10-15

## Active direction — Scope & Pay

On October 15 the user selected idea 1 from the hackathon research: freelance
scope changes, explicit client agreement and payment. Build this complete visible
workflow rather than continuing the merchant-investigation AI extension.

[Product truth](PRODUCT.md), the [build contract](docs/SCOPE-CONTRACT.md) and
[three-stage execution prompts](docs/SCOPE-BUILD-PROMPTS.md) govern this work.
The new homepage is Scope & Pay. Preserve the former console at `/operations`.
Real OpenAI and PayPal acceptance require credentials and measured checks; local
sample review and simulated invoices must remain visibly labelled.

## Previous direction — merchant investigation

On October 14 the user approved adapting this project for the PayPal AI Hackathon
and chose OpenAI for the investigation assistant. They have no PayPal account yet;
prepare and test the integration offline while account access is pending.

The product is now **Payment Incident Copilot**: a merchant investigation workflow
connecting customer complaints, PayPal evidence and application access records.
The first full slice covers paid/access disagreement; duplicate-payment and refund
investigations follow as their provider evidence becomes supported. AI explains
authorized evidence and uncertainty; application code controls actions.

[docs/PAYPAL-HACKATHON-PLAN.md](docs/PAYPAL-HACKATHON-PLAN.md) governs new work and
supersedes the prior deferral of additional providers and AI. Preserve existing
software evidence and simulator functionality. The plan does not declare PayPal,
AI, real merchant need or production acceptance complete. H1 and H2 have offline
implementations: scoped PayPal order/capture reads, verified webhook ingestion,
typed bindings and investigation-only cases. The default deployment remains
simulator-backed; real sandbox acceptance awaits an account. H3 implements the
OpenAI assistant next, with measured evaluation before enabling it.

Use [docs/PAYPAL-SETUP.md](docs/PAYPAL-SETUP.md) and the draft
[docs/AI-SPEC.md](docs/AI-SPEC.md) for integration and evaluation boundaries.

## Portfolio priority

Software engineering is the primary career target. Applied AI engineering is a
secondary target. Favor a useful workflow, reliable implementation, measurable
correctness, and clear engineering tradeoffs.

## Workspace split

- This `ai-payments` folder is for the payment project.
- Data Reliability & Replay is a separate software project. The user will create
  its project folder; its implementation does not belong in this workspace.
- Manufacturing operations remains a future candidate, subject to finding a
  concrete user workflow and representative data.

## Payment project working scope

The proposed product is a Payment Reliability & Reconciliation Console for small
SaaS teams. Its first workflow investigates a successful payment that did not
produce the expected account access in the business's application.

The proposed flow is:

1. Receive and persist verified payment events.
2. Compare payment evidence with application access state.
3. Detect discrepancies and show an evidence timeline.
4. Let an authorized operator preview a repair.
5. Recheck current state, execute an approved repair safely, and record the result.

Engineering depth includes durable processing, recovery after worker failures,
duplicate and out-of-order events, reconciliation, tenant isolation, permissions,
safe retries, and auditability. Demonstrate these with injected failures and
measured correctness.

AI may retrieve evidence, explain discrepancies, and reference deterministic
repair proposals. Application code constructs executable proposals and enforces
permissions, business rules, approvals, and execution.

Later candidates include order/refund reconciliation and explaining payout fees
and adjustments. The user need still requires validation.

## Accepted finishing scope — October 10

The user accepted a bounded finishing pass for this payment project:

1. Reproduce and explain an actual worker death after the target commits, using
   the original operation identity and real grace/lease periods.
2. Measure distinct-purchase investigation and detection under a noisy workspace
   and a worker restart; publish measured limits and failed assumptions.
3. Align setup, capability claims, architecture explanation, and a technical case
   study with the implementation and verification evidence.

The portfolio deliverable is a local, synthetic backend reliability demonstration.
It is not a claim that the original broader production release gate has passed.
AI, financial reconciliation, subscriptions, additional providers, public hosting,
and product validation remain explicitly deferred. Adding these requires a fresh
decision rather than automatically continuing the old phase list.

TraceBack is a separate candidate under assessment. Its research note is in
[docs/TRACEBACK-RESEARCH.md](docs/TRACEBACK-RESEARCH.md); no new project has started.

## Build plan

The proposed scope is expanded into [PLAN.md](PLAN.md), with the technical
contracts in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), verification gates in
[docs/ACCEPTANCE.md](docs/ACCEPTANCE.md), and official-provider constraints in
[docs/RESEARCH.md](docs/RESEARCH.md). Phases 0–4 and the Phase 5 local package are
implemented. The October 10 finishing scope governs the next work; the original
production requirements and product validation remain outstanding.

The bounded finishing pass is complete. Its measured successes, retained failed
runs, two corrective changes and reproduction commands are recorded in
[docs/PORTFOLIO-FINISH.md](docs/PORTFOLIO-FINISH.md). Further product or AI scope
requires a new discussion with the user.

On October 11 the user approved starting the next improvement sequence.
Performance profiling and scheduling are completed locally. The operator UI and
scoped current-record checks are implemented; the evaluated assistant and
deployment remain following phases. See [docs/UI-IMPROVEMENT.md](docs/UI-IMPROVEMENT.md),
[docs/NEXT-IMPROVEMENTS.md](docs/NEXT-IMPROVEMENTS.md) and
[docs/PERFORMANCE-IMPROVEMENT.md](docs/PERFORMANCE-IMPROVEMENT.md).

## Reading the historical context

`overall context.txt` contains earlier brainstorming and conflicting alternatives.
Use this file for the current project split and career priority. Preserve the
historical text as background rather than treating every recommendation as active.
