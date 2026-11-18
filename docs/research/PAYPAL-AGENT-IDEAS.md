# PayPal agent and payout project directions

Researched 2026-10-15. These are product hypotheses for discussion, not an accepted
scope change. No implementation, account setup, transaction, notification or Git
operation was performed. Demand and comparative novelty have not been validated.

## What the resource examples establish

The [hackathon resources](https://paypalaihackathon.devpost.com/resources) suggest
agent checkout, paying contractors after task completion and gig-worker payouts
as example directions. They are inspiration prompts, not finished example
projects or evidence that these products already have customers.

The linked agent-tools reference redirects to an unavailable page in the research
browser. The primary [PayPal Agent Toolkit repository](https://github.com/paypal/agent-toolkit)
currently lists `create_order`, `get_order`, `pay_order`, and `create_refund`,
alongside invoice, dispute and other tools. Its documented list does **not** list a
Payouts tool. `pay_order` is an order payment operation; it is not a contractor
payout. A payout adapter would call the Payouts REST API we implement. The separate
[AI Toolkit plugin](https://github.com/paypal/AI-Toolkit) assists coding agents and
connects sandbox MCP; its developer commands do not supply our product's approval,
budget or recovery logic.

## 1. Contractor completion review to approved payout

**Actor and problem.** A small design or content agency assigns a contractor a
fixed-price task. Work submission, requirements, revisions, approval and payment
currently exist as separate records. A manager needs to determine which milestone
is ready for approval, pay the agreed person and amount, and distinguish a delayed
payout from a task that was never approved. This is a hypothesis to validate with
agency operators, not a proven market claim.

**Specific AI judgment.** Compare a versioned brief, submitted text and revision
discussion with explicit acceptance criteria. Show requirement-by-requirement
evidence, missing deliverables and contradictions; draft a clarification where
acceptance is unclear. For a content demo, one requested legal-review disclaimer
and one requested source citation might be absent. AI flags the omissions and
retains source spans. It does not declare arbitrary software/design quality or
interpret silence as client acceptance.

**PayPal action.** The manager explicitly approves the task version, contractor
identity, agreed USD amount and payment instruction. A deterministic worker then
submits a sandbox payout and tracks item status. PayPal supports single-recipient
and batch payout creation. `sender_batch_id` provides duplicate protection for 30
days; repeated `5xx` requests reuse the same ID. This bounded provider guarantee
does not replace our permanent task-payment uniqueness, immutable approved
payload or reconciliation when an outcome is unknown.
[Payout creation API](https://developer.paypal.com/api/payments.payouts-batch/v1/payouts-post).

**Visible demonstration.** A contractor submits an article against a $150 brief.
The review screen shows two missing criteria and a draft clarification. A revised
submission satisfies the checklist; the manager reviews it and approves exactly
$150 to the registered contractor. Inject a timeout immediately after the provider
accepts the request. The app shows “payment outcome being checked”, restarts the
worker, reads the original payout and displays its actual item result without
creating a new payment. Replaying approval or delivering the same webhook twice
cannot pay the task again. A second scenario leaves a recipient unclaimed and
explains that this is not successful receipt of funds.

PayPal distinguishes pending, successful, failed, unclaimed, returned and other
payout outcomes; unclaimed funds return after 30 days. A batch acceptance response
is not proof every recipient received money.
[Payout processing states](https://developer.paypal.com/payouts/payment-processing/).

**Small MVP.** One agency funding account, one known contractor sandbox recipient,
one fixed-price text deliverable and currency, manual final approval, one payout
item per task. Screens: Tasks, Requirement review, Approve payment, Payment
timeline. No multi-sided marketplace, payroll, custody, escrow, split merchant
payments or assertion that task quality is guaranteed. The agency pays its own
contractor from its own account.

**Access restriction.** Official setup permits sandbox business-to-personal payout
testing; a developer app, both sandbox accounts and app credentials are required.
Live use separately requires a verified business account and Payouts activation.
The overview says sandbox integration can be tested while a live access decision
is pending. Eligibility and funding still need checking; our user has no configured
PayPal account, so neither account access nor a real payout has been verified.
[Payout setup](https://developer.paypal.com/payouts/use-payouts/set-up),
[eligibility and access](https://developer.paypal.com/payouts/use-payouts/overview).
Use an email or PayPal ID in the sandbox; the API documents that sandbox `PHONE`
recipients are unsupported. [Recipient restrictions](https://developer.paypal.com/api/payments.payouts-batch/v1/payouts-post).

**Reuse versus new work.** Current durable jobs, workspace isolation, immutable
evidence, exact approval checks, audit and uncertain-outcome recovery principles
are useful. Existing PayPal order/capture reading and verified webhook patterns
provide a starting point. But our implemented policy is investigation-only and
money writes are unsupported. Task/submission/criterion versions, contractor
identity, payout funding/fees, approval revocation, new payout tables and a Payouts
adapter all need design and implementation. Access-grant receipts are not payout
receipts, and existing capture webhook handling must not be presented as payout
support. [Current verified scope](../PAYPAL-VERIFICATION.md),
[current provider capabilities](../../backend/app/paypal_investigation.py).

**Assessment.** Strongest candidate of these two: a clear actor, tangible action,
meaningful AI reasoning before approval, and visible failure recovery. The hard
product decision is what evidence justifies manager approval; reliable payout
execution then gives our infrastructure a concrete purpose. Major risk: AI review
becoming an unreliable quality score or a redundant checklist. Validate with real
brief/revision examples before building.

## 2. Purchase assistant with a checked purchase mandate

**Actor and problem.** An operations coordinator needs a repeat purchase with
specific constraints: for example, five compatible adapter kits from a known
supplier, delivered by a fixed date, within an all-in budget. A recommendation can
look suitable yet omit shipping, tax, compatibility or a substituted item. A
network failure after checkout also creates uncertainty about whether to buy again.

**Specific AI judgment.** Turn the request into an editable mandate, compare a
small trusted catalog and supplier terms, explain tradeoffs and identify missing
compatibility or delivery facts. It recommends a quote with cited catalog evidence;
it cannot invent stock or shipping guarantees. A deterministic validator rechecks
merchant allowlist, SKU/version, quantity, full price, currency and quote expiry
against the approved mandate before a money operation.

**PayPal action and consent.** A merchant integration can create a PayPal order,
present buyer checkout and capture an approved order. The toolkit's order tools
wrap related APIs, but do not establish open-ended buyer purchasing authority.
An internal mandate is not PayPal payer approval. For a feasible MVP, let the agent
choose and prepare the purchase, have the user complete sandbox PayPal approval,
then let our server validate and capture. Background purchase without that step
would need separately supported consent/vault/payment capabilities and account
eligibility; it is not established by our existing read adapter.
[Standard Checkout](https://developer.paypal.com/checkout/),
[order creation](https://developer.paypal.com/api/orders/v2/orders-create),
[capture API](https://developer.paypal.com/api/orders/v2/orders-capture).

**Visible demonstration.** Request five compatible kits under $100 total. AI rejects
a $90 listing with $20 shipping and flags unsupported compatibility in another.
The user accepts a $95 quote and approves PayPal checkout. A changed $105 price
blocks capture and requests a new decision. For the unchanged quote, inject a lost
capture response and recover the existing order/capture instead of purchasing
again. Show an exact record of the approved quote, executed request and observed
outcome. The recovery and budget checks must be real code, not model assurances.

**Limits and account feasibility.** Keep one owned demo storefront with three
trustworthy catalog records and one sandbox buyer/merchant. Standard Checkout does
not grant a buyer agent payment powers at arbitrary unaffiliated stores. Do not
promise universal shopping, arbitrary browser checkout, reusable buyer consent or
production card-vault availability. Standard sandbox accounts and credentials
must be proven first. Live use requires a business account; a multi-merchant
platform adds a separate PayPal approval/onboarding dependency.
[REST setup](https://developer.paypal.com/api/get-started/),
[platform approval](https://developer.paypal.com/platforms/get-started).

**Reuse versus new work.** Reuse tenant permissions, durable execution, amount and
merchant checks, order/capture bindings, webhook handling and audit patterns. Add
catalog/quote provenance, purchase mandates, spend reservations under concurrency,
checkout creation/capture, buyer approval UI, checkout recovery and expiry rules.
The current read-only PayPal adapter cannot transact. Provider idempotency is
endpoint-specific and time bounded, so never claim unlimited exactly-once charging
from one generic header. [Order request contract](https://developer.paypal.com/api/orders/v2/orders-create),
[existing scope](../PAYPAL-VERIFICATION.md).

**Assessment.** Attractive demo and substantial systems work, but weaker problem
fit for us than contractor payouts. A three-item owned store can feel contrived;
cross-store purchasing introduces integrations and payer-consent complexity well
beyond the present foundation. The category itself is already suggested by the
hackathon, so the constraint/evidence/recovery quality must supply the value.

## Recommendation for discussion

| Candidate | AI work | Visible PayPal result | Product change | Main gate |
| --- | --- | --- | --- | --- |
| Contractor review to payout | Requirements versus submission, ambiguity and revision evidence | Approved contractor payment with actual item-state recovery | Major domain/UI change; infrastructure principles reusable | Validate review usefulness and prove sandbox Payouts access |
| Constrained purchase assistant | Match requirements and total quote; expose missing facts | Buyer-approved checkout and capture | Major buyer/storefront domain and UI change | Prove catalog realism and supported buyer-consent flow |

Prefer **contractor completion review to approved payout** if we want an agent
that visibly takes a useful money action while retaining a precise human decision.
Consider the purchase assistant only if we can name a specific purchasing niche
and obtain credible catalog/quote inputs. Do not combine both into a generic agent
that shops, hires, invoices and resolves disputes for the hackathon.
