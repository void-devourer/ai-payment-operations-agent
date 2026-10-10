# Current project direction

Updated: 2026-10-10

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

## Reading the historical context

`overall context.txt` contains earlier brainstorming and conflicting alternatives.
Use this file for the current project split and career priority. Preserve the
historical text as background rather than treating every recommendation as active.
