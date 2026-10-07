# Problem discovery record

Status: unvalidated hypothesis, 2026-10-07. No customer interview, production
incident dataset, pilot, saved-time measurement, or recovered-revenue claim exists.

## Hypothesis and current workflow to investigate

A small SaaS developer/operator sometimes has a successful payment in the provider
but missing application access. The working hypothesis is that joining payment,
purchase, access, and processing evidence makes diagnosis and controlled repair
faster than switching between the provider dashboard, application database, and
logs. A better native fulfillment integration may be the best solution for some
businesses; discover that before expanding the console.

The reference app and synthetic fault scenarios can establish technical behavior.
They cannot establish how frequent or commercially important this problem is.

## Interview guide

Use 3–5 initial developer/support interviews as a learning sample. Ask about a
recent concrete incident rather than whether someone likes the project idea.

1. What did the customer report, and what access should their purchase have given?
2. Which provider/purchase/access identifiers existed? Which records were missing?
3. What did you inspect, in what order, and which systems/tools did you switch among?
4. What established payment success and refund/dispute state at the time of repair?
5. What was the actual cause, and what evidence distinguished it from a guess?
6. How did you repair it? Who was allowed to act? Could retries cause another effect?
7. How much elapsed and active investigation time did it take? How was that measured?
8. What happened after a later refund/dispute or an intentional access suspension?
9. What does your existing provider dashboard/integration/support tooling already do?
10. What data/API access could an external console have, and what must it never retain?
11. Would improving the fulfillment handler remove this pain without another console?
12. What measurable outcome would justify using a new tool in your workflow?

Request anonymized identifiers and redacted timelines. Do not collect card data,
API keys, raw personal support conversations, or full production database exports.
The user conducts or explicitly authorizes outreach; this project does not send
messages to interview candidates automatically.

## Interview record template

| Field | Record |
| --- | --- |
| Participant pseudonym / date / role | Pending |
| Business workflow and payment/access architecture | Pending |
| Incident trigger and expected outcome | Pending |
| Anonymized timeline and available exact identifiers | Pending |
| Existing diagnosis/repair tools and approval constraints | Pending |
| Measured elapsed time / active operator time / measurement method | Pending |
| Recurrence and severity, with supporting examples | Pending |
| Privacy/integration constraints and required retention | Pending |
| Alternative fix and reason a console would/would not help | Pending |
| Pilot decision and concrete success measure | Pending |

## Assumptions that can change scope

| Assumption | Evidence needed | Current state |
| --- | --- | --- |
| Incidents recur enough to justify investigation tooling | Recent incident examples and frequency | Unvalidated |
| Teams can register exact purchase/provider/access bindings | Architecture/API walkthrough | Unvalidated; reference app will demonstrate |
| Operators need supervised repair beyond better normal fulfillment | Actual repair workflow and alternatives | Unvalidated |
| Conditional target writes and durable receipts are feasible | Implemented adapter and failure tests | Planned in Phase 1 |
| Core evidence reads are affordable and available | Sandbox adapter, permissions/budgets, then pilot | Not yet verified |
| Joined evidence reduces effort | Baseline versus supervised comparison with same scenarios | No measured result |

Continue the technical simulation while discovery is pending. Revise the product
if credible incidents lack exact bindings, native integration fixes remove the
need, or repair authority cannot be established. Keep production/business claims
separate from synthetic correctness and benchmark evidence.
