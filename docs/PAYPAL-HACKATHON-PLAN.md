# Payment Incident Copilot — PayPal AI Hackathon

Historical direction, superseded 2026-10-15 by
[Scope & Pay](SCOPE-CONTRACT.md). The PayPal order/capture integration remains
available in the preserved console; new product work follows freelance scope
review, explicit client acceptance and invoicing.

Accepted direction: 2026-10-14. This document governs the new hackathon work;
historical local-release evidence remains valid for the tested simulator scope.

## Product and problem

A merchant support operator receives an ambiguous customer complaint, such as
"I paid but cannot use my purchase" or "I think I was charged twice." They need
to connect the customer's claim with PayPal records and their application's
purchase/access history, decide what the evidence establishes, and choose a
specific next step without treating a customer statement as provider truth.

The product is an evidence-grounded investigation workspace. The assistant
interprets the complaint, explains agreement/conflicts across records, identifies
unknowns, and drafts an editable customer reply. The operator retains the
decision. A useful result can be a supported escalation or a request for missing
records; every investigation need not produce an automatic repair.

This keeps software engineering as the primary portfolio focus while making AI
a meaningful part of the support workflow. It reuses the existing durable jobs,
tenant isolation, case history and conditional access-repair machinery.

## Hackathon obligations

The [official rules](https://paypalaihackathon.devpost.com/rules) require a working
project using PayPal sandbox technology and AI. Existing projects need
significant progress during the event. Record the starting revision, additions
and verification evidence clearly. Deadline: **2026-11-13 01:30 IST**.

Prepare a public repository with an open-source license, complete run instructions,
an English project description and a public YouTube demonstration under three
minutes. A hosted demo is optional. Keep the judge-access path usable through
the end of judging. Registration, public submission and
selection/publication of the project license require their own concrete review;
none has been performed by this scope change.

## Demonstration scenarios

| Complaint | Evidence to inspect | Demonstrated decision |
| --- | --- | --- |
| Paid, access missing | Linked order/capture, purchase expectations, access and fulfillment history | Distinguish paid/access disagreement from unconfirmed payment; repair only if the provider policy is supported and eligible |
| Possible duplicate payment | All registered attempts/captures for the purchase, amounts and reversal coverage | Explain multiple records without assuming duplicate money movement or selecting a refund |
| Refund seems unresolved | Known refund status, related capture, business access and coverage | Distinguish pending/confirmed/unknown; identify the next check or escalate |

The first complete product slice is the paid/access investigation. Duplicate and
refund investigations follow once the required provider records are available.
Disputes are relevant blocking/review evidence, not a promise to implement dispute
resolution, submit documents, or model the full dispute lifecycle by the deadline.

## Non-negotiable boundaries

- PayPal is the target provider; the independent simulator remains available for
  reproducible faults and development while credentials are unavailable.
- Sandbox success is not live payment, payout, bank settlement or production
  acceptance. Do not claim merchant demand or saved revenue without evidence.
- Preserve typed order/capture/refund identifiers and exact seller/buyer binding.
  Do not quietly repurpose a Stripe payment-intent field as every PayPal object.
- Incomplete refund/dispute coverage must stay incomplete. PayPal repair stays
  disabled until a provider-specific capability and policy review establishes
  the required evidence. A known capture alone cannot satisfy the old policy.
- AI gets authorized, bounded, redacted case evidence and policy context. It has
  no payment-write, repair, approval, SQL, arbitrary URL or external-message tools.
- Application code creates proposals, validates fresh facts and permissions,
  applies conditional grants and verifies recovery. AI prose cannot enable actions.
- Public deployment cannot expose the current local fixture identities. A
  dedicated webhook ingress is separate from a public operator console.

## Delivery sequence

| Phase | Concrete result | Gate / current state |
| --- | --- | --- |
| H1 — provider foundation | Sandbox-only OAuth/capture client, strict scoped facts, credential template and explicit smoke command | Implemented offline; 15 contract tests pass. Account-managed acceptance pending |
| H2 — PayPal investigation | Order/capture bindings, read collection, verified durable webhook path, case projection and provider capability matrix | Implemented and verified offline; genuine account/delivery acceptance pending. Reversal inventories and PayPal repair unsupported |
| H3 — AI investigation | Complaint input, structured OpenAI explanation with evidence links, uncertainty and editable reply | Design draft in [AI-SPEC.md](AI-SPEC.md); implementation and measured evaluation pending |
| H4 — product/demo | Coherent merchant UI, three-minute demonstration and judge-ready runnable release | Not implemented; review real feature coverage before publishing |

H2 and H3 may share fixtures and evidence contracts, but the model must not be
enabled against undefined provider facts. Freeze one complete flow before
broadening to extra features. Allow account setup and user discovery to run
alongside offline development.

## Initial verification and acceptance

For PayPal: test exact binding, authorization vs capture, wrong seller/buyer,
partial/full refunds, unresolved disputes, malformed values, token expiry,
rate limits, incomplete pages, webhook rejection/duplicates/order changes and
worker restart. Run real sandbox acceptance separately from mocked contracts.

For AI: use the [AI design and evaluation contract](AI-SPEC.md). Compare the
assistant against the deterministic console, retain failures, and report model,
prompt, dataset, latency and cost versions. A correct citation ID does not prove
the statement is supported by that evidence.

For the product: demonstrate complaint → actual PayPal/app records → grounded
explanation → human decision → documented or verified outcome. Obtain feedback
from a few support/developer users if possible; label synthetic-only validation
explicitly. Do not claim that adding an AI summary establishes real-world impact.

## Current access and status

H1 verification on 2026-10-14: all 100 unit tests passed (including 15 new
PayPal contracts). The documentation checker passed for 28 documents and all
46 existing acceptance IDs. The smoke command's help and missing-profile path
were checked without provider requests; an absent profile produces a clear
configuration error. Git ignore checks confirmed that `.env.paypal` is ignored
and `.env.paypal.example` is available for version control. `git diff --check`
reported no whitespace errors. These checks establish offline foundation
behavior, not genuine PayPal acceptance or an implemented AI assistant.

H2 implementation on 2026-10-15: the worker and console now support optional
PayPal sandbox configuration and typed bindings. Its independent investigation
policy always requires human review and cannot authorize a repair. The UI shows
order/capture references and makes incomplete reversal history explicit. A local
reference target can model missing access without simulator registration. See
[PayPal setup](PAYPAL-SETUP.md) for limits and enablement.
Recorded H2 checks and remaining gates are in [PayPal verification](PAYPAL-VERIFICATION.md).

The user has no PayPal account yet and selected OpenAI for the assistant. No real
PayPal request or OpenAI call has been made during H1/H2. The default website
still runs the existing simulator flow. Real account/delivery acceptance is
pending; synthetic fixture verification does not close that gate.

The existing framework is FastAPI/Pydantic/PostgreSQL/React. Use the official
OpenAI Python SDK with one bounded Responses call first. Add agent orchestration
or tool loops only if measured evidence-retrieval needs justify them.
