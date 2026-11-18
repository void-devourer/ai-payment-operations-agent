# PayPal sandbox preparation

Updated 2026-10-15. Account access is pending. PayPal is connected to the console,
durable worker and case projection behind explicit sandbox configuration. Offline
tests use synthetic provider responses and real isolated PostgreSQL databases.
The normal local deployment still uses the simulator; real PayPal acceptance is
not established by these tests.

## Account setup

Scope & Pay currently invoices in USD only. The first real sandbox test created
a draft successfully but its India sandbox seller rejected activation with
`INR_FOREIGN_CURRENCY_BLOCKED`. For a USD sandbox demonstration, use a separate
US Business sandbox account and Merchant app with Invoicing enabled. Store that
distinct seller/app in Workspace B rather than changing Workspace A's immutable
connection or presenting sandbox success as live merchant eligibility.

1. Create/sign in to a [PayPal developer account](https://developer.paypal.com/).
   Complete any account agreements yourself. Use the sandbox environment.
2. Obtain a sandbox seller/business account and a sandbox REST app associated
   with that seller. Keep a separate sandbox buyer for testing checkout later.
3. Obtain that app's sandbox client ID and secret and the sandbox seller's merchant
   ID. A merchant ID is distinct from an app ID, order ID and email. For Scope &
   Pay invoicing, these three fields are sufficient; a webhook is optional.
   The older purchase investigation flow additionally needs a linked sandbox
   buyer ID for trusted purchase registration; an email does not substitute for it.
4. Copy `.env.paypal.example` to the ignored `.env.paypal`, then fill its fields
   locally. Leave the existing simulator `.env` alone. Do not paste credentials
   in chat or commit them.

The client exchanges credentials for an OAuth token, caches it until shortly
before expiry, and uses it for order/capture reads on a fixed sandbox origin. It
ignores resource links and disables redirects. Errors contain categories rather
than upstream bodies, credentials or bearer tokens.

## Genuine capture smoke check

When a sandbox checkout has produced a capture, use its exact order and capture
IDs. The current client supports USD only:

```powershell
python scripts/check_paypal_sandbox.py --capture-id YOUR_CAPTURE_ID --order-id YOUR_ORDER_ID
```

The command performs token exchange and a capture read; it does not create,
capture or refund a payment. It checks capture/order/seller binding, supported
status, decimal amount and timestamps. Missing credentials stop before network
access. Its output explicitly reports incomplete provider acceptance.

## What this read cannot establish

- Orders, authorizations, captures and refunds are distinct objects. An approved
  order is not equivalent to a completed capture.
- The capture status and gross amount do not establish full refund or dispute
  history, buyer binding, first-success timing or external bank settlement.
- Unknown/missing facts must stay unknown. Capture-only evidence cannot enable
  the existing access-repair policy.
- The smoke command checks only a capture. The integrated worker additionally
  verifies the linked order, exact buyer/seller, registered capture set and an
  unchanged order read at the end. Both paths remain investigation-only.

## Enable the optional integration

If invoicing is enabled in the sandbox app but the invoice API still returns
HTTP 403, inspect the granted token scopes. Requesting another token can reuse
permissions from before the setting change. During local setup, terminating that
temporary token using PayPal's `POST /v1/oauth2/token/terminate` and requesting a
replacement resolved this condition. Restart the console and console worker
afterward to clear their in-memory token caches. Keep all tokens private; this
is a setup diagnostic, not a retry policy for invoice writes.

Fill `PAYPAL_WORKSPACE_A_CLIENT_ID`, `PAYPAL_WORKSPACE_A_CLIENT_SECRET`,
`PAYPAL_WORKSPACE_A_MERCHANT_ID` in the ignored profile. A webhook ID is optional
for invoicing and status polling. To enable verified incoming events, also set
`PAYPAL_WORKSPACE_A_WEBHOOK_ID`; without it the webhook endpoint stays disabled.
Keep `PAYPAL_ENVIRONMENT=sandbox` and `PAYPAL_ENABLED=1`. Workspace B is optional
and requires a distinct seller/app and, when configured, webhook destination. Then run:

```powershell
docker compose -f compose.yml -f compose.paypal.yml up -d --build --wait
```

Startup rejects incomplete configuration and a changed seller for an existing
connection. Credentials reach only the console API/worker, not the reference or
simulator services. To return to the default deployment, run the base Compose
file without the PayPal override.

The business server, using its workspace's registration credential, registers:

1. `POST /api/purchases` with `connection_id=paypal_ws_a`, the expected USD amount,
   application customer/product and exact PayPal buyer ID.
2. `POST /api/purchases/{purchase_id}/paypal-orders` with `{"order_id":"..."}`.
3. `POST /api/purchases/{purchase_id}/paypal-captures` with
   `{"order_id":"...","capture_id":"..."}` for each known capture.

These relations are immutable. Webhook metadata cannot create them. Register an
order even before it has a capture; the workspace can investigate an approved
order without falsely declaring it paid. The worker supports one purchase unit,
PayPal wallet buyer identity, CAPTURE intent, USD, at most five registered orders
and twenty total registered order/capture references per purchase. Multi-unit,
card-only, AUTHORIZE, refund inventory and dispute inventory are outside this slice.
Unknown or additional captures make the observation incomplete until the trusted
server registers their references. Sweeps cover registered purchases of all ages;
they do not discover the seller's entire transaction inventory.

For the local paid/access demonstration, `POST /demo/paypal-targets` on the
reference application accepts purchase/customer/order IDs under its checkout
credential. This creates inactive access with no provider mutation or simulator
outbox. Register the corresponding purchase explicitly on the console. The
PayPal target cannot use the simulator's `/pay` route.

## Webhook verification and remaining acceptance

Real webhook delivery needs a publicly reachable HTTPS listener. Design a
dedicated ingress exposing only the webhook path; do not expose the current
fixture-login console or the internal business APIs through a tunnel. The path
is `/webhooks/paypal/paypal_ws_a`. The implementation uses PayPal's remote
verification endpoint with the configured app-owned webhook ID and sandbox-only
certificate URL allowlist. Only exact `SUCCESS` permits durable receipt storage.
Verification outages return 503; signature failures return 400. Receipt storage
and any job enqueue commit before acknowledgement. Exact duplicates do not
schedule another read; conflicting bytes for the same event ID return 409.
Events are hints to reread current records, never authoritative snapshots.

Capture completed/pending/denied/reversed and order approved/completed events
with supported resource version 2.0 trigger registered reads. Refund hints route
only when the body provides a related capture ID; unsupported shapes/versions
are quarantined. Dispute events are retained as ignored receipts in this slice;
there is no claim of complete dispute coverage. Registration and periodic sweeps
recover events that arrived before a purchase binding. PayPal's mock webhook
simulator cannot establish genuine app-owned webhook acceptance, and its mock
events do not support the postback verification endpoint.

Genuine order/buyer/capture reads, app-owned signed delivery, rejection and replay
remain acceptance gates once an account is available. Access repair stays disabled
for every PayPal case, regardless of AI output or capture status.

## Primary references

- [PayPal authentication](https://developer.paypal.com/api/rest/authentication)
- [Capture details](https://developer.paypal.com/api/payments/v2/captures-get)
- [Payments API schema](https://developer.paypal.com/api/payments/v2/schema.json)
- [Order details](https://developer.paypal.com/api/orders/v2/orders-get)
- [Verify webhook signature](https://developer.paypal.com/api/webhooks/v1/verify-webhook-signature-post)
- [Webhook integration](https://developer.paypal.com/api/rest/webhooks/rest/)

Offline verification: `python -m unittest discover -s tests/unit -v`, followed by
`python scripts/check_paypal_contracts.py` with local PostgreSQL running. The latter
creates isolated console/reference scratch databases and removes only those
databases after the tests. No provider request is made by either suite.
Actual account, capture and webhook acceptance remain untested until access exists.
