# Account-managed Stripe test integration

Updated 2026-10-09. The account-managed adapter and local contracts are implemented.
A separate genuine temporary-sandbox smoke test passed. Full adapter acceptance
remains open: the temporary key cannot read account identity or disputes. The user
has no account-managed sandbox and Stripe India registration requires an invitation.

## Temporary verification result and isolation

With the user's authorization, a fresh anonymous CLI sandbox was provisioned using
the previously approved Git author email. It expires on **2026-10-16**. The old
anonymous profile was not reused. Secrets/profile/listener output remain ignored.

`scripts/check_stripe_temporary.py --create-fixtures` passed against genuine Stripe:
successful test payment, independent current Charge/Refund reads after partial and
full refunds (PaymentIntent stays succeeded), manual capture with zero received
amount, and seven genuine signed webhook deliveries at `2026-09-30.endive`; none
were rejected. The sanitized local report is `.local/stripe-temporary-verification.json`.
This smoke test does not establish complete reversal coverage or runtime evidence
integration: `/v1/account` and `/v1/disputes` both returned HTTP 403.

The runner accepts only a fresh `rkcs_test_` profile, checks expiry, binds a temporary
loopback receiver on port 8010, verifies raw-body signatures and event scope/version
using the application's ingress functions, and stops its listener/receiver on exit.
It never configures the console, writes either application database, or changes
`.env.stripe`. The permanent simulator stack therefore needs no Stripe credentials
and continues working after the sandbox expires. Full account-managed acceptance
below remains a separate gate; partial verification is not a reason to weaken it.

To reproduce, install the local Stripe CLI, create a fresh profile under ignored
`.local/stripe-verification-profile.toml` using `stripe sandbox create --config ...`,
and capture its output privately (it contains credentials/claim links). Then run:

```powershell
python scripts/check_stripe_temporary.py --create-fixtures
```

Synthetic Stripe fixtures are retained; no live money is used. This opt-in test is
excluded from CI and creates no persistent dependency on the temporary sandbox.

## Implemented boundary

The optional console adapter uses direct REST over pinned HTTPX 0.28.1, with
`Stripe-Version: 2026-09-30.endive` on every request. There is no Stripe SDK dependency.
It accepts only account-managed `rk_test_`/`sk_test_` keys and test resources; the
outbound origin is fixed to `https://api.stripe.com`. It has no POST/DELETE/provider
write method. Runtime credentials belong only to the console API/worker. The
separate acceptance runner has explicit test-only fixture creation and its writer
credential lives in `.env.stripe-fixtures`, never in console containers.

At startup a server-owned `stripe_ws_a`/`stripe_ws_b` connection is inserted once
and checked for immutable account/environment/version. Each observation verifies
the reader's account, exact registered customer/intent, optional metadata cross-check,
and live-mode rejection. Current PaymentIntents, every relevant Charge, and all
bounded refund/dispute pages are read independently. Contradictory reversal totals
or changing payment state cause retryable incomplete evidence. Optional settlement
facts remain incomplete. Existing lease, generation, request/response/time/page
bounds and append-only evidence rules apply unchanged.

`POST /webhooks/stripe/{destination}` uses `Stripe-Signature`, the configured
destination secret, raw bytes, recency and the same atomic inbox/job transaction.
Direct-account events may omit `account`; the destination secret binds them to the
configured account. Supplied foreign account/Connect context is rejected. Unsupported
authentic versions are quarantined. No simulator header or secret authenticates
the Stripe route. Thin events, Connect and live mode are unsupported.

## Account step the user must complete

1. Open [Stripe registration](https://dashboard.stripe.com/register), create your
   account with accurate details, and complete its authentication steps.
2. Open an account-managed sandbox. Follow
   [Stripe's sandbox management](https://docs.stripe.com/sandboxes/dashboard/manage).
   If signup limits prevent access, report that result; do not invent business details.
3. Obtain a sandbox reader key with Account, PaymentIntent, Charge, Refund and
   Dispute read permissions, and the destination signing secret. A full test key
   is supported for local development, but a restricted reader is preferable.

Create `.env.stripe` by copying [the blank template](../infra/stripe.env.example).
Populate the local account ID, reader key and destination secret; set
`STRIPE_ENABLED=1`. Never paste the secrets into chat or a GitHub issue.

Start the optional integration:

```powershell
docker compose -f compose.yml -f compose.stripe.yml up -d --build --wait --wait-timeout 180
```

The sandbox must emit snapshot events using exactly `2026-09-30.endive`. Configure
the destination version explicitly. For local forwarding, the installed CLI's
`listen --latest` currently requests the latest version; it does not pin a future
version. A changed version is quarantined rather than silently normalized. Verify
the emitted `api_version` before accepting a genuine test result.

For the local CLI workflow, use an account-managed CLI login or a test key through
`STRIPE_API_KEY` in the process environment; never a command-line key argument or
the old anonymous profile. Forward only self-account snapshot events to
`http://127.0.0.1:8000/webhooks/stripe/stripe_ws_a`, with the implemented event families.
Use `--latest --events-from @self --all-snapshot --forward-to ...`. Save the matching
CLI-forwarding signing secret in `.env.stripe`, then recreate the two console
containers. A CLI secret differs from a Dashboard destination secret.

## Genuine acceptance runner

Put a separate account-managed test fixture key in ignored `.env.stripe-fixtures`:

```text
STRIPE_TEST_FIXTURE_KEY=<your sandbox test secret key>
```

With the stack and authentic forwarding running, execute:

```powershell
python scripts/check_stripe.py --create-fixtures
```

It verifies reader/writer account identity before creating synthetic customers,
payments, partial/full refunds, manual-capture authorization and a test dispute.
It verifies genuine signed inbox delivery and complete runtime observations.
Provider test writes exist only in this explicitly invoked acceptance script;
they are not console features. Synthetic fixtures are retained for inspection.
The internal development-only reference target is created without a simulator
outbox, so the same purchase cannot be registered under both providers.

The runner has finite request/poll bounds, produces no secret output, fails closed
on missing credentials/permissions/versions, and saves a sanitized success report
only after all checks pass. A timeout or unsupported sandbox behavior leaves the
genuine gate open. Do not run it in load tests or feed it live keys.

Without credentials, `python scripts/check_stripe.py` returns exit code 2 with
the explicit configuration blocker. CI runs offline fixtures via
`scripts/check_stripe_contracts.py`; it never reads private sandbox secrets or
labels fixture signatures as genuine Stripe delivery.

Local checks passed: 63 unit tests, four PostgreSQL-backed offline Stripe contracts,
and the existing Phase 1/2 regressions. Hosted CI runs the offline suites only;
genuine account-managed acceptance is still blocked on the account step above.
The temporary smoke result is additional, limited evidence, not that acceptance.

## Primary sources

[API versioning](https://docs.stripe.com/api/versioning),
[signature verification](https://docs.stripe.com/events/manage-webhook-endpoints#signature-errors),
[Charge pagination](https://docs.stripe.com/api/charges/list),
[Refund pagination](https://docs.stripe.com/api/refunds/list),
[Dispute pagination](https://docs.stripe.com/api/disputes/list),
[test payment methods and disputes](https://docs.stripe.com/testing).
