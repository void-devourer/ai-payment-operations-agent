# PayPal hackathon product shortlist

Research: 2026-10-15. Discussion only. No direction has been selected by the user,
and this note does not replace the active plan or authorize an implementation.

## What the examples establish

The [official resources](https://paypalaihackathon.devpost.com/resources) provide
inspiration prompts for agents, money movement, businesses, consumers and social
impact, plus API/tool links. They are not detailed case studies or evidence of
customer demand. The ideas below combine those prompts with this codebase's
existing evidence, approval and recovery infrastructure.

Native capabilities matter: PayPal already has [invoices, reminders and payment
links](https://developer.paypal.com/invoicing/about), and a [Resolution Center and
Disputes API](https://developer.paypal.com/platforms/disputes/overview). Upwork
already supports [milestones and change requests](https://support.upwork.com/hc/en-us/articles/360000990268-How-to-add-or-edit-milestones-on-Upwork).
Bonsai already exposes [AI-accessible invoice creation and updates](https://docs.hellobonsai.com/).
We should not describe any of those broad categories as novel.

## Comparison

| Candidate | Specific user problem | AI responsibility | PayPal role | Actual change from our app |
| --- | --- | --- | --- | --- |
| Agreed scope → invoice | Direct-client freelancers lose track of which requested changes were actually agreed and priced | Compare a versioned brief with messages, cite additions/contradictions and draft a change request | Create an approved invoice and reconcile payment status | Major domain/UI rebuild; reuse infrastructure and provenance/approval principles |
| Contractor delivery → payout | Small agencies review scattered deliverables and separately track who should be paid | Compare a submission to the work brief and flag missing or contradictory items for owner review | Submit an explicitly approved payout and reconcile its item status | Major; new tasks, recipients, budgets, payout adapter and financial recovery |
| Dispute evidence workbench | Merchant must answer a specific buyer claim using scattered agreement/delivery records | Build a sourced chronology, identify missing proof and propose a reviewed packet | Read the dispute and submit reviewed evidence where API access permits | Medium/major; strongest reuse of our case/evidence model, but new adapter and document workflow |
| Approved digital delivery | Client approval, paid amount and delivered asset version disagree | Check acceptance criteria against delivery notes and explain mismatches | Checkout/capture tied to a particular delivery | Medium/major; closest access/delivery reuse, weaker differentiation unless versioned agreement is central |

These are relative engineering judgments, not delivery estimates or market scores.
No demand or hackathon-winning potential has been proven.

## Preferred direction: agreed scope to invoice

Focus on independent web designers/developers or small studios serving clients
directly. The proposed product starts with a brief and a conversation, not an
accounting dashboard. Example:

1. Original agreement: one landing page, one revision, $500.
2. Client messages contain an included revision, an ambiguous request for a second
   page, and a separately agreed $120 addition.
3. AI maps each candidate change to source spans and the applicable brief version.
4. Freelancer reviews the interpretation; client explicitly accepts the updated
   scope and price in the product. A suggested change is not silently billable.
5. A reviewed PayPal invoice requests the accepted addition's payment.
6. Payment status is linked back to that exact accepted scope version.

The [Invoicing API](https://developer.paypal.com/api/invoicing) supports separate
draft creation and sending. It requires a business account with Invoicing enabled
and sandbox credentials; access needs an early real test. Proposed AI and client
acceptance behavior are application features we would build, not PayPal features.

Interesting software decisions: source identity and repeat imports, versioned
scope, consent versus requests, deterministic prices, stale approval invalidation,
one logical invoice per accepted change, and endpoint-specific timeout/recovery.
Current access-grant receipts do not implement those financial semantics.

Small demonstration: one brief, a pasted conversation, three deliberately
different request types, one reviewed change, client acceptance and sandbox
invoice payment. Exclude a full CRM, mailbox integration, tax engine and escrow.

Validation before expansion: inspect real anonymized examples with a few
freelancers. Check whether the tool finds useful changes, asks the right
clarifications, avoids falsely claiming agreement and saves work over their
current process. Test and retain ambiguous/contradictory examples. Do not infer
value merely from a successful invoice API call.

## Other directions and decisive risks

**Contractor delivery → payout:** a good action-oriented alternative, especially
for one bounded deliverable type such as subtitle files. AI can assist review;
the owner authorizes completion and the exact amount/recipient. PayPal's
[Payouts API](https://developer.paypal.com/api/payouts) supports batch creation and
item status. Batch acceptance does not prove every recipient was paid. A meaningful
demo includes an uncertain response and recovery without blindly issuing a new
payout. Our existing approval/worker patterns transfer; money-write semantics,
funding, account access and recipient/budget models are new. This is not escrow.

**Dispute evidence:** likely the most coherent evolution of our existing cases.
The evidence must include omissions favorable to the buyer, not manufacture a
merchant defense. PayPal decides the dispute outcome. Its [sandbox dispute-creation
guide](https://developer.paypal.com/platforms/disputes/integrate-disputes) documents
an additional scope enabled through an account manager. That specific API test path
must be proven before making dispute submission the only working demo; this does
not establish that every manual sandbox path is unavailable.

**Approved digital delivery:** preserves the most current payment/access behavior,
but payment-gated downloads alone are common. The interesting version connects
accepted asset versions and missing acceptance criteria to recoverable delivery.
We would need an explicit new delivery policy; current PayPal access repair is
disabled and must not be silently enabled.

## Recommendation for the next discussion

Prefer **agreed scope to invoice** for a stronger business product with a visible
before-and-after workflow. Prefer **contractor delivery to payout** if the user is
more interested in agent actions and financial execution. Prefer **dispute
evidence** if continuing the merchant-operations domain matters most and access can
be demonstrated. Keep the approved-delivery idea as the closest-reuse alternative.

Choose one primary workflow. Combining all four would create a broad business
platform before any single user problem has been validated. Generic AI invoice
generation, payment summaries and shopping chat alone would add less differentiation.

Detailed business research: [business directions](PAYPAL-BUSINESS-IDEAS.md).
Agent execution and account-access research: [agent and payout directions](PAYPAL-AGENT-IDEAS.md).
