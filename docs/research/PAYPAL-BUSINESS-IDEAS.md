# PayPal + AI business project directions

Research date: 2026-10-15. These are candidate product directions, not an accepted
scope change. Only this research note was created. No account, transaction,
customer message, source code or active plan was changed.

## What the resources page actually suggests

The [hackathon resources](https://paypalaihackathon.devpost.com/resources) offer
illustrative ideas across agent automation, money movement, business, consumer
and social-impact experiences. Business examples include freelancer invoicing,
creator payments and marketplace checkout. These are inspiration prompts, not
evidence that a particular idea has customers or that a specific API is enabled
for our account.

The three ideas below are product hypotheses. The API abilities are sourced;
their proposed usefulness and differentiation are our judgment. We have not
interviewed freelancers, proven demand, measured saved time or verified our
PayPal account access.

## 1. Agreed scope to invoice: a freelancer change-order assistant

**Actor and problem.** A freelance designer/developer agrees to a fixed-price job.
Later messages mix clarifications, revisions, additional deliverables and proposed
price changes. The freelancer needs to know which work is actually agreed, which
is merely requested, and what can be billed without inventing client consent.

**Specific AI work.** Compare a versioned project brief and an uploaded conversation
export. Produce a structured change ledger: added/removed deliverables, supporting
message spans, explicit agreement versus ambiguous language, and unanswered
questions. Draft a change-order confirmation and invoice line items using only
operator-approved rates. The model never infers a binding agreement from silence
or decides that a client legally owes a charge.

**Meaningful PayPal operation.** After a freelancer reviews the agreed scope and
the exact amount, create a PayPal draft invoice; approve activation and expose the
hosted payment link; read invoice status and recorded payment information.
PayPal's API separates draft creation from sending, so an AI draft need not notify
anyone. Invoicing requires a business account with Invoicing enabled and sandbox
credentials. [API quickstart](https://developer.paypal.com/api/invoicing),
[invoice reference](https://developer.paypal.com/invoicing/reference/).

**Demo narrative.** A $500 landing-page brief includes one design revision. A chat
contains “Could we add a second page?”, “Maybe later”, and a later explicit
agreement to a $120 addition. AI identifies the unapproved request and accepted
addition with source quotes. The freelancer corrects one item, approves the $120
invoice, the sandbox client pays, and the project records the payment against the
accepted change. A duplicate callback cannot produce a second change invoice.

**Differentiator.** PayPal already creates invoices, tracks status and provides
reminders. The proposed value is reconciling messy scope negotiations before
billing, retaining the connection between an invoice line and its approved
agreement, and catching contradictions. A generic natural-language invoice
generator would be weak. [Native invoicing capabilities](https://developer.paypal.com/invoicing/about).

**MVP bounds.** One freelancer, one client, one currency, text brief and pasted
conversation, fixed operator-entered rates, explicit client acceptance in an app
screen, one change invoice and sandbox payment. No mailbox OAuth, international
tax engine, automatic collections, legal contract interpretation, recurring
retainers or multi-merchant onboarding. The user-facing screens are Project,
Proposed changes, Client acceptance and Invoice/payment timeline.

**Reuse and changes.** Reuse tenant isolation, evidence snapshots, immutable audit
history, fresh approval checks and durable reads. Add brief/message provenance,
scope versions, client acceptance and an Invoicing adapter; substantially replace
the current incident-console UI. Existing access-repair execution cannot simply
be reused for invoice writes: each endpoint needs its own duplicate protection
and unknown-outcome reconciliation.

**Largest risk.** Confusing a request or suggested price with consent. Explicit
acceptance is the product's boundary; ambiguous messages must remain unresolved.
This direction also needs early proof of sandbox Invoicing access.

**Assessment.** Strongest fresh business story and most distinct visible product
of these three. More redesign, but the existing evidence/approval architecture
has a clear purpose in it.

## 2. Payment-to-delivery workspace for bespoke digital work

**Actor and problem.** A designer sells a particular asset version or a freelancer
delivers a defined milestone. The team must link exactly what the client approved,
what payment was captured and which version was made available, including when
payment notifications or delivery workers fail.

**Specific AI work.** Convert a brief into a proposed acceptance checklist; compare
uploaded delivery notes and client feedback with that checklist; highlight missing
or contradictory acceptance evidence. Draft a precise handover summary. An AI
assessment does not establish that the client accepted delivery or that the
artifact satisfies a contract.

**Meaningful PayPal operation.** Use a genuine sandbox Checkout order and capture
for a client-approved deliverable, then release its application download permission
after current payment checks. Orders support server-side creation and buyer
checkout. Payment authorization and capture are separate states; authorization
alone is not paid delivery. [Checkout guide](https://developer.paypal.com/checkout/),
[Orders create API](https://developer.paypal.com/api/orders/v2/orders-create/).

**Demo narrative.** A client approves design version 3, pays through PayPal, and a
worker crashes before providing its download link. The workspace reconstructs the
approved version and captured payment, explains the precise delivery gap, and
resumes one delivery operation without creating another charge. A revision request
for version 4 stays a separate decision. AI asks about a missing criterion rather
than labelling the whole job complete.

**Differentiator.** Payment buttons and “unlock after payment” are common. The idea
becomes worthwhile only if versioned agreement, AI-assisted acceptance review and
observable delivery recovery are central. PayPal can already support order
management and shipment/refund workflows; it does not make our local design
approval, asset-version provenance or recovery state automatically authoritative.
[Native Checkout features](https://developer.paypal.com/checkout/).

**MVP bounds.** One bespoke digital deliverable, manual client acceptance, one USD
capture, a short-lived application download link and explicit recovery audit.
No escrow, held freelancer balances, platform/seller payment splits, automatic
milestone payouts or claims that PayPal guarantees completion. Long projects
should not be modelled as indefinitely renewable payment authorizations.

**Reuse and changes.** Closest to the current purchase/access system: durable jobs,
payment binding, reference target and repair history are relevant. New work is
checkout creation/capture, delivery versions, object storage and a client portal.
The current PayPal provider contract disables access repair because reversal and
dispute inventories are incomplete; this idea requires an explicit new
delivery-policy design, rather than silently enabling the old repair predicate.
[Current provider policy](../../backend/app/paypal_investigation.py).

**Largest risk.** Turning the current narrow access bug into a prettier screen
without stronger acceptance/version reasoning. PayPal freshness, unknown payment
outcomes and delivery-link security also require careful design.

**Assessment.** Best reuse, moderate visible redesign, weaker originality unless
the agreed-deliverable/version model is compelling.

## 3. Service-delivery evidence builder for disputes

**Actor and problem.** A small agency receives a “service not received” or “not as
described” claim. Contract changes, messages, delivery records and acknowledgments
sit in different places. The operator needs an accurate response that also admits
missing or contradictory evidence.

**Specific AI work.** Match the actual dispute reason to relevant agreement and
delivery evidence; extract source-linked dates, build a factual chronology,
identify contradictions and missing proof, and propose an editable evidence packet.
This is reason-specific evidence assembly and coverage checking, beyond a chat
summary. A timestamped upload or internally generated log does not prove the buyer
received or accepted the service.

**Meaningful PayPal operation.** Read a dispute's reason and requested evidence;
assemble a reviewed response and, only after an explicit approval, submit supported
notes/documents through `provide-evidence` where available. The APIs support
reason-specific evidence and multipart attachments. PayPal/banks determine the
case outcome. [Dispute evidence guide](https://developer.paypal.com/disputes/reasons-evidence/),
[Disputes API](https://developer.paypal.com/api/disputes/).

**Demo narrative.** A dispute claims no service was delivered. AI finds a handover
message and client response but flags that one promised revision remains absent.
The operator excludes an unrelated project attachment, reviews the claim-linked
chronology and submits the packet. The system records the approved payload and
submission state without claiming victory. The helpful outcome can be acknowledging
a real omission rather than maximising merchant wins.

**Differentiator.** PayPal already has Resolution Center, buyer messaging and dispute
responses. Our candidate advantage is extracting and verifying evidence from the
merchant's work records, reason-specific missing-proof checks, provenance and
submission recovery. “AI replies to disputes” alone is an unconvincing duplicate.
[Native dispute tools](https://developer.paypal.com/platforms/disputes/overview).

**MVP bounds.** One dispute reason, manually uploaded text/documents, one merchant,
one reviewed packet; no broad fraud model, legal advice, automatic refunds,
automatic buyer messages, predicted win percentages or generated evidence. If API
access is unavailable, export is useful but cannot be called a genuine PayPal
dispute submission.

**Reuse and changes.** Strong reuse of cases, evidence provenance, workspace
permissions, audit and approval. Add Disputes adapter, source ingestion/document
handling, evidence-type mapping and submission reconciliation. Replace the current
access-centric screen with a dispute/evidence timeline.

**Largest risk.** Account/API access, then evidence truthfulness. The official guide
documents buyer-side sandbox dispute creation with `DISPUTE_CREATE` scope and says
to contact a PayPal account manager to enable it. This is a gate for that API
simulation method, not proof all manual sandbox dispute paths are inaccessible.
Prove a usable end-to-end test path before choosing this as the headline demo.
[Official sandbox integration requirements](https://developer.paypal.com/platforms/disputes/integrate-disputes).

**Assessment.** Strongest evolution of the current investigation product, but a
less accessible hackathon demo until account permissions are proven. Better as a
later feature of idea 1 or 2 than the only promised working flow today.

## Suggested decision

| Candidate | Business story | Reuse | Product change | Biggest validation question |
| --- | --- | --- | --- | --- |
| Agreed scope to invoice | Clear before-payment workflow | Infrastructure and evidence principles | Major domain and UI change | Do freelancers actually struggle to distinguish agreed changes from requests? |
| Payment-to-delivery | Clear sale and recoverable delivery | Highest | Medium/major UI plus delivery domain | Is version/acceptance confusion frequent enough to justify a separate tool? |
| Dispute evidence builder | Concrete high-consequence investigation | High | Medium/major evidence UI | Can we obtain the needed sandbox/API access, and do operators trust sourced drafts? |

Recommendation: explore **agreed scope to invoice** first if a substantially better
business product is the goal. It has a specific AI reasoning job, a meaningful
PayPal action, a visible client-facing workflow and a concrete human judgment
boundary. Validate it with a few examples from freelancers before expanding.
Do not combine all three into a generic freelancer operating system for the
hackathon. No idea has been accepted or implemented by this research.
