# Phase 0 contracts

Contract baseline: 2026-10-07. These define the interfaces to implement in later
phases. The pure policy in [policy.py](../backend/app/detection/policy.py), Phase 1
registration/target contracts and Phase 2 simulator ingestion/current-read path
are executable. Detection integration and console approval/execution remain later
work; see [Phase 1](PHASE-1.md) and [Phase 2](PHASE-2.md).

## Supported purchase and exact identities

The reference application sells one-time digital access. Its trusted backend
creates a provider customer and payment attempt and registers immutable purchase
expectations. The console never creates bindings from an email, an amount match,
or a browser-supplied metadata field. Currency is a lowercase three-letter code;
amounts are nonnegative integer minor units, with positive amounts required by
the first policy. Never accept floats or booleans as amounts.

Proposed `POST /api/purchases` registration body, version `purchase_v1`:

```json
{
  "contract_version": "purchase_v1",
  "workspace_id": "ws_a",
  "purchase_id": "purchase_a",
  "customer_id": "customer_a",
  "product_id": "product_a",
  "expected_access": "digital_pass",
  "expected_amount_minor": 2500,
  "currency": "usd",
  "connection_id": "conn_a",
  "provider_customer_id": "cus_a"
}
```

The authenticated integration determines allowed workspace and connection. It
cannot select arbitrary scope by changing this body. The server resolves the
connection's provider account and environment. Repeating identical registration
returns the existing purchase; changing immutable values returns a conflict.
The reference app commits registration to its own outbox alongside its purchase.

Append payment attempts through
`POST /api/purchases/{purchase_id}/payment-attempts` with an immutable
`payment_intent_id` and optional `checkout_session_id`. A scoped provider object
can belong to only one purchase. Distinct purchases with equal amounts remain
distinct. Multiple attempts belong to one purchase; they do not multiply access.
The first reference product maps explicitly to one target access record; product
mapping registration and versioning are Phase 1 responsibilities.

## Observation contract and policy inputs

Normalize retrieved facts into these internal records:

| Record | Required meaning |
| --- | --- |
| `ProviderScope` | Workspace, connection, provider account, and `simulated` / `test` / `live` environment |
| `AccessBinding` | Exact workspace, purchase, business customer, and product |
| `Purchase` | Trusted binding and scope; provider customer; unique registered PaymentIntent IDs; expected amount/currency |
| `EvidenceWindow` | Aware start/end timestamps and explicit completeness |
| `PaymentEvidence` | Selected intent/status/received amount/currency; successful registered attempts; refund/dispute history counts; payment and reversal windows; persisted first verified success time |
| `AccessEvidence` | Exact binding, explicit status, revision, whether access has ever activated, and observation window |

`payment_window.complete` means authorized current reads cover **all registered
attempts**, not just the selected intent. Select the sole successful attempt for
evaluation when one exists. If several succeeded, the policy requires review.
`reversal_window.complete` requires relevant Charge reads and all relevant
refund/dispute pages; denied reads, failed pages, or unknown fields remain
incomplete. Counts include any history, including pending/failed refunds and
historical disputes. `access.window.complete` requires an authoritative target
read. Missing fee/settlement information is separate and does not block core
access eligibility when these three bundles are complete.

The normalizer records source, resource IDs, request interval, provider/API/
normalizer version, and content digest alongside these facts in Phase 2. A
webhook snapshot alone cannot establish current eligibility. Metadata is a
cross-check against trusted registration, never its replacement.

Persist `first_confirmed_succeeded_at` the first time current provider evidence
confirms success for the selected attempt. Re-reading unchanged success must
not restart grace. It is a console confirmation time, not PaymentIntent creation
time or an assumed settlement time. A later different successful attempt has
its own confirmation time. Missing or future confirmation cannot authorize a
missing-access candidate.

## Pure decision contract

`evaluate_access(purchase, payment, access, now=..., active_operation=...)` returns
an immutable `Decision` with `outcome`, stable reason codes, and policy version
`one_time_access_v1`. Defaults: 120-second grace and at most 60-second-old evidence.
Freshness uses the oldest read in each observation interval. Exactly 60 seconds
is accepted; grace expires at exactly 120 seconds. Clock inputs are explicit and
timezone-aware. The clock is supplied by trusted application code, not a client.

| Outcome | Meaning |
| --- | --- |
| `eligible` | All core evidence permits preparing a missing-access proposal |
| `pending` | Payment is not yet successful or normal fulfillment is within grace |
| `healthy` | Current paid-access predicate is satisfied by already-active access |
| `blocked` | Unsupported live/zero-price path, failed/canceled payment, or intentional/previous access block |
| `awaiting_evidence` | Missing, incomplete, stale, inconsistent, unknown, or incorrectly scoped facts |
| `manual_review` | Reversal history, multiple successes, or paid value mismatch |
| `operation_in_progress` | An active or uncertain repair already exists |

Precedence: unsupported purchase/environment; missing observations; exact scope;
freshness/completeness; reversal/multiple-success review; state consistency;
payment success/value; access state; grace; existing operation; eligibility.
Consequently, a refund/dispute on active access remains a review finding. Fresh
active access resolves only the paid-missing-access predicate, never a reversal
review or an uncertain operation receipt.

`eligible` is a proposal candidate. It does not authenticate an actor, approve an
action, create a job, or execute a request. Phase 4 must enforce current membership,
exact approved payload, expiry, policy version, access revision, and repeated
provider/access reads immediately before dispatch. Phase 3 must atomically enforce
case deduplication; Phase 4 must enforce one active/uncertain operation in the DB.

## Written happy path

1. The reference app registers `purchase_a` for `customer_a` / `product_a`, USD
   2,500 minor units, `conn_a`, `cus_a`, and `pi_a`.
2. Its normal fulfillment is deliberately interrupted in a synthetic scenario.
3. Current evidence in the matching account/environment confirms `pi_a` succeeded,
   received exactly 2,500 USD minor units, and is the only successful attempt.
   Complete current reversal reads show no refund/dispute history.
4. Authoritative access is never-activated `inactive`, revision 0. At 120 seconds
   after persisted success confirmation, all observation windows are fresh.
5. Policy returns `eligible` / `paid_access_missing`. The case workflow can prepare
   an immutable proposal with these evidence references and revision 0.
6. An authorized operator approves that exact proposal. Approval and operation/job
   creation commit together. The executor repeats authorization and eligibility.
7. The target conditionally activates access and commits the operation receipt in
   the same target transaction. A fresh access read verifies business recovery.

Steps 1–4 are supported on the synthetic Phase 1/2 API path. Step 5 is a tested
pure policy, with console integration still due in Phase 3. Step 6 and the console
orchestration around step 7 remain Phase 4 gates. Phase 1 implements the target's
conditional-write/receipt contract and ordinary fulfillment; no money moves.

## Target repair and uncertain outcome

Planned request to `POST /internal/access-grants`, authenticated as a scoped
console integration, with version `access_grant_v1`:

```json
{
  "contract_version": "access_grant_v1",
  "operation_id": "op_a",
  "workspace_id": "ws_a",
  "purchase_id": "purchase_a",
  "customer_id": "customer_a",
  "product_id": "product_a",
  "expected_revision": 0,
  "expected_status": "inactive",
  "proposal_id": "proposal_a",
  "policy_version": "one_time_access_v1",
  "expires_at": "2026-10-07T12:10:00Z"
}
```

The server, not the model/browser, creates this payload. The target authenticates
and validates binding before exposing any receipt. Hash the canonical validated
payload with deterministic field ordering. One target transaction claims the
unique operation ID, checks any prior payload hash, checks target preconditions,
updates access/revision, and stores its immutable receipt. Identical retries
return that receipt; changed payload with the same ID is a conflict. An already
active, suspended, revoked, or previously activated target cannot be reinstated
by this contract. Receipt lookups require primary reads and authenticated scope.

After a lost response, retain `outcome_unknown` and query
`GET /internal/operations/{operation_id}`. Never invent a new operation ID to
escape uncertainty. A missing receipt may mean an in-flight transaction and
does not prove no effect. Preserve identity/receipt records through the allowed
retry horizon. There is no cross-system transaction preventing a provider
reversal after the final check; later reconciliation must detect that change.

Unsafe cases and release checks are also enumerated in [ACCEPTANCE.md](ACCEPTANCE.md).
