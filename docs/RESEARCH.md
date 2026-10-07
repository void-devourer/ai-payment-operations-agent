# Stripe integration research

Source check date: **2026-10-07**. Scope: a Payment Reliability & Reconciliation Console for small SaaS teams, starting with a paid one-time purchase whose access grant is missing from the business application.

This document separates documented provider behavior from proposed project decisions. It is documentation research, not verification of this user's account, API credentials, or a deployed integration. No account was provisioned and no Stripe request was executed.

## 1. Product boundary and existing functionality

Stripe's Checkout fulfillment documentation explicitly includes provisioning access to services and requires the integrator to implement safe repeated/concurrent fulfillment and record its result. A customer might never visit the success page; asynchronous payment methods can complete later. The cross-system fulfillment gap is therefore a credible engineering problem category. Whether small SaaS teams need this particular console remains a user-validation hypothesis. [Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment?payment-ui=stripe-hosted)

Workbench already exposes API request logs, object inspection, event deliveries, errors, and resend controls. Stripe's payout reports already reconcile provider-side transactions. Smart Retries already schedules retries of failed invoice payments. Approval rules already control selected sensitive provider actions, including refunds. [Workbench](https://docs.stripe.com/workbench/overview), [Payout reports](https://docs.stripe.com/reports/payout-reconciliation), [Smart Retries](https://docs.stripe.com/billing/revenue-recovery/smart-retries), [Approval rules](https://docs.stripe.com/account/approvals)

**Product inference:** the useful difference is joining Stripe facts to the application's order, access, and processing records; detecting a business outcome that never happened; and proving a controlled repair. A webhook log viewer, generic payment dashboard, or custom retry optimizer alone duplicates substantial existing functionality.

**MVP decision:** the console's operational mutation is a business-app access grant. It has **no Stripe refund, charge, capture, cancellation, payout, or dispute-submission endpoint**. A separate companion application's sandbox checkout creates payments for demonstration. Refunds and disputes are observed as evidence and policy blockers, not executed by the console. Read-only financial reconciliation can follow the initial access-repair workflow.

## 2. Event receipt, authentication, and delivery

### Documented behavior

- Stripe recommends asynchronous processing and a quick `2xx` response. Delivery is not guaranteed to be ordered; snapshot timestamps are only second-resolution and cannot establish sequence. Repeated deliveries can share an event ID; distinct events can describe equivalent business effects. Live webhook retries continue for up to three days; sandbox events retry three times over a few hours. Dashboard resend is available up to 15 days and CLI resend up to 30 days. Manual resend does not cancel automatic retries. Official libraries check signature timestamps with a default five-minute tolerance; setting tolerance to zero disables that recency protection. [Webhook delivery and security](https://docs.stripe.com/webhooks)
- Signature verification requires the exact raw request body, `Stripe-Signature`, and the destination's signing secret. Parsing, reserializing, or otherwise modifying the body first can invalidate verification. CLI-forwarded and Dashboard-managed destinations have different secrets even though both begin with `whsec_`. [Signature handling](https://docs.stripe.com/events/manage-webhook-endpoints#signature-errors)

### Project decisions

Persist-before-acknowledgment is **our durability design**, not an explicit atomic persistence guarantee provided by Stripe. After authentication and environment checks, one database transaction records the event receipt and its durable processing job; only a successful commit permits `2xx`. Database failure returns a retryable error. The worker performs provider lookups and business logic later. Acknowledgment means durable receipt, not completed fulfillment.

Use a receipt uniqueness key scoped by provider account, sandbox/live environment, and event ID. Separately protect business effects using the purchase and operation identity. Do not globally suppress every `(resource ID, event type)` pair: repeated legitimate updates can share that pair.

Keep SDK recency verification enabled and clocks synchronized. Store receipt and event times separately. A valid signature authenticates the sender; it does not prove business ownership or repair eligibility. Permit only a configured event allowlist, preserve unknown-version events for investigation, and never route a simulator event into a live connection.

## 3. Snapshot/thin formats and API versions

Current documentation recommends **thin events for new integrations**. Thin notifications identify an event/resource; the application can fetch the complete event or current resource. Thin events cover both `/v1` and `/v2` resources, and their notifications are unversioned. Snapshot payloads carry a point-in-time resource representation and are versioned; their destination API version is fixed at creation. Snapshot data may be stale when processed, so current-state actions should retrieve the resource. Stripe retains snapshot support for complete-payload integrations, historical resource views, and change auditing. [Event formats](https://docs.stripe.com/events/how-events-work)

The snapshot Event object's `api_version` describes the rendering of its immutable `data`; fetching an old event with a newer API version does not rewrite its history. [Event object](https://docs.stripe.com/api/events/object)

**Proposed bounded choice:** use one explicitly version-pinned snapshot destination for the first release if captured historical receipt payloads are part of the incident evidence requirements. Record that rationale instead of claiming snapshot is Stripe's current default recommendation. If Phase 0 instead selects thin notifications, use the matching SDK parser and Events v2 API; do not mix snapshot field assumptions into that implementation. Support one format initially.

Select and record an available stable API/SDK pair during implementation. Pin outbound request version, destination version, dependency version, fixture version, and normalizer version. Do not copy a preview version from a documentation example without deciding to accept preview behavior. Store raw authenticated evidence separately from normalized projections and use fixture contract tests before upgrades.

## 4. Payment completion is distinct from refund/dispute eligibility

PaymentIntent statuses are `requires_payment_method`, `requires_confirmation`, `requires_action`, `processing`, `requires_capture`, `canceled`, and `succeeded`. `requires_capture` represents authorization awaiting capture, not completed payment. [PaymentIntent object](https://docs.stripe.com/api/payment_intents/object)

Checkout completion alone is insufficient for delayed payment methods. Stripe's fulfillment guide checks the retrieved Session's `payment_status` and handles `checkout.session.async_payment_succeeded`; a success-page redirect alone is unreliable. [Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment?payment-ui=stripe-hosted)

Charge fields separately expose `amount_refunded`, `refunded`, and `disputed`. `refunded` remains false for partial refunds. Refund statuses include `pending`, `requires_action`, `succeeded`, `failed`, and `canceled`. Disputes have independent warning, review, response, won/lost, and prevented states. [Charge object](https://docs.stripe.com/api/charges/object), [Refund object](https://docs.stripe.com/api/refunds/object), [Dispute object](https://docs.stripe.com/api/disputes/object)

**Contract-derived conclusion:** a successful PaymentIntent can remain `succeeded` after a refund; its status has no refunded/disputed variant. Therefore `PaymentIntent.status == succeeded` cannot establish that money has not been returned or contested. Verify the selected API version empirically with a sandbox test that retrieves the PaymentIntent, Charge, and Refund after full and partial refunds. No such test has been run during this research.

**MVP repair policy:** require a newly retrieved successful PaymentIntent tied to the known purchase, matching expected amount/currency/account/environment, and complete Charge/refund/dispute observations. Any refund history or dispute history initially routes to manual investigation; future policies may distinguish resolved cases. Missing, inaccessible, stale, or contradictory evidence blocks repair. Free orders, subscriptions, discounts, tax recalculation, manual capture, and partial fulfillment require separate explicit rules and are outside the first contract.

An old success event must never overwrite newer refund/dispute knowledge. Separate payment, refund, dispute, and business-access state in the data model. Do not automatically revoke access after a partial refund: access policy depends on the product and purchased units, not solely money arithmetic.

### Minimal event coverage

For snapshot format, consider the following bounded families:

| Family | Candidate events | Purpose |
| --- | --- | --- |
| PaymentIntent | `payment_intent.succeeded`, `.processing`, `.payment_failed`, `.canceled` | Trigger current payment observation |
| Checkout | `checkout.session.completed`, `.async_payment_succeeded`, `.async_payment_failed`, `.expired` | Mapping and checkout lifecycle |
| Refund | `refund.created`, `.updated`, `.failed`; `charge.refunded` | Refresh reversal facts |
| Dispute | `charge.dispute.created`, `.updated`, `.closed` | Refresh contested-payment facts |
| Later finance | `charge.updated`, `payout.reconciliation_completed`, payout lifecycle events | Delayed financial data and payout attribution |

Subscribe only to families implemented by that release. For thin format the catalog uses corresponding `v1.*` names, including `v1.payment_intent.succeeded` and `v1.checkout.session.completed`; verify exact supported names at setup. Event receipt triggers observation, not an immediate entitlement decision. [Thin event catalog](https://docs.stripe.com/api/v2/core/events/event-types), [Refund events](https://docs.stripe.com/refunds#refund-events)

## 5. Mapping and access credentials

Metadata can hold internal record IDs, but it is mutable and is not copied automatically across every related object. Checkout Session metadata and `payment_intent_data.metadata` are distinct assignments. Stripe documents setting the latter to populate the underlying PaymentIntent. Never put sensitive payment/bank data in metadata. [Metadata](https://docs.stripe.com/metadata)

**Mapping decision:** create the purchase server-side and persist account/environment, application customer, product, expected amount/currency, Checkout Session ID, and eventual PaymentIntent ID. Write opaque purchase IDs into both relevant metadata locations server-side. Cross-check the persisted binding; metadata alone, email matching, amount similarity, or an LLM's interpretation cannot authorize access. Distinct legitimate purchases of identical amounts remain distinct.

Stripe recommends restricted API keys with configured permissions. Sandbox and live resources use separate credentials and cannot be accessed across modes. Webhook signing secrets are separate from API keys. Secret/restricted keys belong on servers, outside source control and browser code. [API keys](https://docs.stripe.com/keys), [Key protection](https://docs.stripe.com/keys-best-practices)

Separate the console's reader credential from the companion checkout creator credential. The reader receives only the resource reads needed for reconciliation. Define a server-side connection registry; clients do not supply credentials, account IDs, or tenant identities for privileged work. Use a read-only provider interface for the console and a separately authenticated business-app repair interface.

## 6. Backfill and coverage limits

Events v1 can list events only within the last 30 days, and their historical payloads retain their original rendering. [List Events](https://docs.stripe.com/api/events/list)

Stripe documents recovering undelivered events with event-type filtering, pagination, and `delivery_success=false`. That flag covers failed delivery to at least one destination; it does not isolate the console's destination. Recovery can race with ordinary delivery and must deduplicate. An event processed manually can still arrive through automatic retry. [Undelivered-event recovery](https://docs.stripe.com/events/manage-webhook-endpoints#process-undelivered-events)

**Recovery decisions:** scan an overlapping, checkpointed time window for every implemented event type; route recovered receipts through the same durable inbox. Advance the checkpoint only after the complete page/window succeeds. Track coverage and surface partial scans, permission errors, expired history, and API failures.

`delivery_success=false` cannot discover an event our endpoint acknowledged before a later worker/business-action failure. Add resource-to-business-state reconciliation independent of event delivery. Revisit mapped purchases and incomplete jobs; a new-order window alone misses later refunds on old purchases. Backfill beyond provider retention needs our own retained evidence and current-resource reads, and cannot reconstruct every historical transition. Display unknown/incomplete coverage rather than asserting that no discrepancies exist.

## 7. Idempotency and the external-action boundary

Stripe stores the first executed response for an idempotency key, including `500` responses; matching retries return that stored result. Keys can be pruned after at least 24 hours, after which reuse can cause a new execution. Reusing a key with changed parameters is rejected. Validation failures and conflicting concurrent executions do not store a completed idempotent result. `POST` accepts idempotency keys; they have no effect on `GET`/`DELETE`. [Stripe idempotency](https://docs.stripe.com/api/idempotent_requests)

Refunds can be partial, multiple, pending, or failed. They cannot total more than the original charge. Bank-debit refunds and disputes can create double-reimbursement risk. Those facts rule out an unrestricted refund agent even in a later release. [Refund behavior](https://docs.stripe.com/refunds)

**Project contract:** provider idempotency keys do not protect the application's access endpoint. Require the companion app to persist an operation ID, exact payload digest, grant, and result receipt in one transaction. A repeat of the same operation returns its stored result; a different payload with that ID is rejected. Enforce a purchase-level grant uniqueness constraint across independently generated operations too.

After a timeout, query operation status and current access state before deciding to retry. If the target lacks durable idempotency or a verifiable operation receipt, ambiguous outcomes enter `outcome_unknown` and require investigation. Do not create a new operation ID to escape ambiguity.

There is no atomic transaction spanning Stripe and the business app. A refund can happen between a provider read and an access grant. Recheck immediately before execution, bind approval to the evidence/policy versions, and detect subsequent changes through reconciliation; document this remaining race. Promise at-least-once job execution with bounded, demonstrably idempotent business effects under this adapter contract, **not universal exactly-once external actions**.

## 8. Financial reconciliation boundaries

Automatic payout composition can be queried from BalanceTransactions filtered by payout ID after reconciliation completes. Stripe explicitly cannot assign individual transactions to a merchant-chosen manual payout. [Payout reconciliation API](https://docs.stripe.com/payouts/reconciliation)

Payout reconciliation reports require automatic payouts, apart from the documented connected-account exception. Instant payout composition is also the merchant's responsibility. Manual-payout users should use balance-style reconciliation. [Payout reports](https://docs.stripe.com/reports/payout-reconciliation)

BalanceTransactions provide signed integer `amount`, `fee`, and `net` in their currency's minor units; `net = amount - fee`. Their settlement currency can differ from the payment's presentment currency. Model currency explicitly and include non-charge movements rather than assuming payment totals equal a payout. [BalanceTransaction object](https://docs.stripe.com/api/balance_transactions/object)

Asynchronous capture can leave a successful payment's Charge `balance_transaction` temporarily null. `charge.updated` later indicates availability. Missing immediate fee/settlement data must mean pending observation, not zero fees or a confirmed discrepancy. [Asynchronous capture](https://docs.stripe.com/payments/payment-intents/asynchronous-capture)

Financial CSV reports use decimal major units, unlike integer minor-unit API values. Reports have their own data-availability windows and run asynchronously. Certain report flows require live keys, and sandboxes do not emit `reporting.report_type.updated`. [Reports API](https://docs.stripe.com/reports/api)

**Later-release decision:** initially use fixed-currency, read-only, versioned fixtures plus available sandbox resource observations for finance demonstrations. Mark fixtures clearly. Do not require live financial reports to finish a sandbox portfolio MVP. Import real permitted reports only in a separately reviewed live integration. Never infer actual bank receipt solely from expected payout status or estimated arrival dates.

## 9. Sandboxes, India availability, and performance tests

Indian business accounts remain invite-only. Stripe's public support page states that new India businesses must request an invitation; existing active accounts remain supported. This constrains live-business onboarding assumptions, not proof that every development path is unavailable. [India account availability](https://support.stripe.com/questions/moving-to-invite-only-in-india)

The current official **[Sandboxes documentation](https://docs.stripe.com/sandboxes)** separately documents anonymous coding-agent sandboxes through `stripe sandbox create --help`, with working keys and no account registration. It recommends general sandboxes for new integrations and separate environments for local development/CI. The same page lists unsupported IC+ pricing tests and connections between platform/connected-account sandboxes.

**Unknowns:** this research did not provision an anonymous sandbox. Its lifecycle/expiry, renewal, account-region restrictions, Dashboard access, webhook-destination creation, restricted-key permissions, and supported financial-report features have not been verified. The documentation reviewed does not establish those lifecycle details. Phase 0 must inspect the installed CLI help and verify the exact supported workflow before relying on it. Do not create a fictitious non-India business account to bypass onboarding restrictions.

Testing environments do not move real funds. Use test keys and documented test payment methods; Stripe says not to test live mode with real payment details and not to use test environments for load tests. [Testing](https://docs.stripe.com/testing)

Stripe discourages sandbox load testing and recommends configurable API mocks. Sandbox latency is not representative of live card-network behavior. The documented global limits are 100 requests/second live and 25 requests/second sandbox, with endpoint/resource/concurrency limits as well. Rate-limit responses need bounded exponential backoff with jitter. Limits are ceilings, not benchmark targets. [Rate limits and load testing](https://docs.stripe.com/rate-limits)

**Performance decision:** run high-volume receipt, concurrency, backlog, restart, and repair tests against local provider/target doubles with explicit simulated latency. Keep genuine sandbox acceptance tests small. Report hardware, workload, latency distributions, error rate, and mock assumptions; do not claim those measurements establish Stripe throughput or production financial correctness.

## 10. Proposed minimal integration contract

The following is project design, not a Stripe-provided guarantee:

1. **Business scope:** one-time, fixed-price digital access; one provider account per connection; one currency per purchase; no stored PAN/CVC; no Connect or recurring billing in the first contract.
2. **Connection:** server-owned tenant/account/environment binding, pinned versions, least-privilege reads, separate signing secret. Demo deployments accept sandbox resources only.
3. **Purchase binding:** server-created purchase and expected financial/product values linked to provider IDs. No fuzzy identity matching.
4. **Receipt:** authenticate the untouched body; atomically commit inbox/job before acknowledgment; deduplicate receipts while preserving processing state.
5. **Observation:** worker retrieves current payment, Charge, complete relevant refunds/disputes, and current target access. Persist source/time/version for each observation and distinguish unavailable evidence from negative evidence.
6. **Detection:** a payment/access mismatch becomes an exception after a configured fulfillment grace period. A failed background job can be investigated immediately. Deterministic rules produce the finding and eligibility result.
7. **Approval:** an authorized human approves an exact access-repair proposal tied to purchase, target, evidence digest, policy version, and expiry. Re-check authorization and current evidence at execution. A stale/blocked proposal cannot execute.
8. **Target mutation:** use a durable operation ID, idempotent target transaction, grant uniqueness, and stored receipt. Timeouts resolve through status observation; unresolved cases are visible.
9. **Resolution:** confirm target state and receipt before marking repaired; record actor, intent, policy, evidence, attempts, and outcome. Evidence change after repair triggers a new investigation.
10. **Recovery:** checkpointed overlapping backfill plus periodic business-state reconciliation; visible provider coverage; safe worker leases and retries.
11. **AI:** consume sanitized, tenant-scoped evidence through bounded read tools. Return cited explanations and proposal text; no provider or business-app execution credential, permission authority, amount calculation, or policy override.

## 11. Feasibility and validation gates

Before committing implementation dependencies:

- Confirm anonymous CLI sandbox availability, expiry/renewal, permission boundaries, and supported Checkout/event operations; otherwise use an existing authorized sandbox. Retain a deterministic fixture mode regardless.
- Select event format/API version and demonstrate the same purchase mapping on checkout and PaymentIntent observations.
- Prove raw-body verification, environment mismatch rejection, duplicate handling, and persistence failure before acknowledgment.
- Retrieve PaymentIntent/Charge/Refund after full and partial refunds; verify no access repair can rely on `succeeded` alone. Test dispute evidence separately.
- Demonstrate target operation idempotency, repeated proposals, concurrent approvals, client timeout after target commit, and status-query recovery.
- Verify revoked/insufficient reader permissions and provider timeouts yield incomplete evidence, not repaired cases.
- Clearly distinguish mock demonstrations, genuine sandbox checks, and future live-user validation. No production-readiness or customer-demand claim follows from documentation alone.
