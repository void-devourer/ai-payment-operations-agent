# Performance, operator experience, and investigation assistant

Scope draft, 2026-10-10; performance completed locally 2026-10-11 after the
user approved starting. This records the improvement sequence requested by the user.
The previous bounded local finishing pass is complete; this document does not
declare these improvements implemented or authorize public deployment.

Performance progress and evidence: [PERFORMANCE-IMPROVEMENT.md](PERFORMANCE-IMPROVEMENT.md).
UI and AI implementation remain separate upcoming phases.

## Concrete problems

1. The historical-inventory benchmark missed its declared deadline. Existing
   reports measure the outcome but do not isolate time spent waiting in the
   queue, requesting source evidence, waiting for request budgets, or publishing.
2. The interface exposes internal codes and long identifiers as its primary
   labels. A long evidence history overwhelms the summary and available actions.
3. `Refresh evidence` currently reloads stored API records. It does not enqueue
   an authoritative source read, so its label promises more than its behavior.
4. The assistant exists only as a design in PLAN.md. Its usefulness must be
   measured against a clear deterministic investigation view.

## Performance experiment

Reproduce a declared large inventory and noisy-workspace workload in an isolated
Compose project. Preserve the same input scenarios, request budgets, resource
limits, worker count, timeout, and expected outcomes for before/after runs.
Record the registered inventory, queued backlog and injected faults separately.
Existing historical results remain evidence; they are not a controlled baseline
for a differently populated future run.

Measure receipt-to-claim queue delay, collection duration, source HTTP latency,
request-budget deferrals, retries, database query/transaction time, and time
spent on scheduled sweep work. Keep missing outcomes in the denominator and
report each workspace separately. A CPU profile alone cannot explain queue or
network waiting.

Rank hypotheses only after the reproduction exists. Possible experiment targets
include sweep competition with new work, sequential workspace service, budget
deferrals, and database work. These are questions, not diagnosed bottlenecks.
Change one variable, rerun the same workload, then run correctness regressions.
Do not raise provider budgets, shorten grace, remove negative cases, or drop
old purchases to manufacture a pass. The result may be a declared sustainable
capacity rather than satisfying the original large-inventory target.

## Operator interface

Use a classic light layout, readable system typography, restrained status colors
and consistent spacing. A case inbox opens a dedicated investigation view rather
than cramming every section into a narrow selector/detail layout.

The investigation hierarchy:

1. Business finding, purchase amount/product, case status, last checked time.
2. Current evidence freshness and a clear available next action.
3. Payment attempts and application access in readable summaries/tables.
4. Evidence, assistant, and activity sections; recent evidence initially visible,
   with older checks expandable and technical references collapsed.

Keep complete identifiers accessible in technical details/copy controls. A short
display reference must not pretend to be a customer name or a unique business
identifier. Use explicit label mappings rather than underscore replacement.
Examples: `PAYMENT_REVIEW` becomes `Payment needs review`; the reason
`multiple_successful_attempts` becomes `Multiple successful payment attempts`;
`Disposition` becomes `Close case with a reason`. Backend codes remain stable.

For the user's example, preserve both messages: the last recorded check found
two successful $25 payment attempts, while current evidence is out of date.
Do not claim a duplicate charge is confirmed or suggest an automatic refund.

Separate `Reload view` from `Check latest records`. The latter needs an
authenticated, scoped, rate-limited backend enqueue operation and visible
queued/running/complete/failure status. It must preserve retry backoff and cannot
promise an immediate check. A read-only viewer's allowed check permissions must
be designed explicitly; the model does not gain enqueue authority.

## AI workflow and implementation boundary

Frontend: an `Assistant` section within an investigation, with `Explain this
case` and scoped follow-up questions. It references the same case the operator
is reviewing, with clickable evidence and the snapshot time.

Backend: an authenticated case-assistant endpoint and a separate assistant
module. Server code loads a bounded, redacted evidence bundle for the authorized
case plus relevant versioned policy text. The model receives no database
credentials, raw SQL interface, payment keys, arbitrary customer lookup, or
repair/approval/refund tools. API keys remain server-side.

Start with a server-assembled bundle and one bounded model call. Add read-only
tool retrieval only if larger histories or evaluation results justify it; every
tool derives workspace and purchase scope from the authenticated case. The
existing PLAN.md read-only tool contract remains the boundary. A vector database
is not required to send an authorized case snapshot and short policy excerpt.

Model output contains an explanation, supported findings with evidence IDs,
unknowns, and suggested investigation steps. Validate its schema and ensure all
cited IDs belong to the supplied evidence. Valid citations alone do not prove
the explanation is supported; evaluation must check that separately. Display
the server-computed eligibility and repair status independently of generated
text. Generated prose never enables a repair button.

Bind responses to observation IDs, policy version and generation. If the head
changes, mark the explanation as belonging to an older snapshot. Stale or partial
input supports a historical explanation and a request for further checks, not a
fresh operational conclusion. Current payment/access evidence does not establish
payout settlement or explain an unobserved causal failure.

Useful tasks:

- Explain differences across checks: what changed and what remains unknown.
- Explain why the deterministic policy blocks a repair, with cited facts/rules.
- Answer bounded questions about this case's evidence and uncertainty.
- Draft an editable internal handoff note; no automatic external messages.

For the example: explain that two successful attempts were recorded against
one purchase, so policy requires review; say the snapshot is stale; suggest
checking current attempts and refund history. Do not claim why the attempts
occurred when no evidence establishes that cause.

## Evaluation and ordering

Proposed order: performance reproduction/profile and correction; operator UI
including real check status; evaluated assistant; deployment readiness review.
The assistant's design and UI placement are agreed before implementation.

Use the existing PLAN.md / ACCEPTANCE.md AI protocol: reviewed development and
frozen holdout scenarios, repeated trials, and a deterministic non-AI baseline.
Cover stale/partial evidence, multiple attempts, refunds/disputes, intentional
access blocks, uncertain repair outcomes, tenant boundaries, malicious text,
provider failures, and snapshot changes. Measure supported explanations,
appropriate uncertainty, citation correctness, usefulness, latency and cost.
User discovery is needed to establish real operator usefulness; synthetic
evaluation alone cannot establish it.

Timeouts, model errors, disabled AI, and exhausted budgets leave normal
investigation usable. Keep the assistant experimental until its declared gate
passes. Production planning then addresses hosting, TLS, identity, secrets,
quotas, monitoring and restore. Simulator-only hosting must be labelled as such;
it does not complete real Stripe acceptance.
