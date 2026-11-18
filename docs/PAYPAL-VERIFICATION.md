# H2 PayPal investigation verification

Date: 2026-10-15. Status: offline implementation verified; real sandbox acceptance
pending account access. No PayPal or OpenAI request was made by this verification.

## Delivered behavior

Authenticated business registration binds separate order and capture IDs to one
purchase and provider connection. The worker reads each order, verifies the wallet
buyer and seller, checks the complete registered capture set, reads each capture
and rereads the order for changes. It independently reads application access.
Lease and evidence-generation checks fence publication; jobs survive restarts.
Sweeps and operator checks schedule purchase-based reads without synthetic payment
intent IDs. The existing simulator/Stripe job contracts remain available.

App-owned PayPal webhook postback verification must return `SUCCESS` before a
receipt can be persisted. Receipt and scheduling commit atomically. Duplicate
delivery cannot create another job; changed bytes for an existing identity are
rejected. Old event snapshots cannot overwrite freshly read provider facts.

PayPal cases use `paypal_investigation_v1` and require review. They cannot enter
the access-repair policy. The console labels capture/order records separately and
shows unknown reversal history explicitly. The independent reference application
can create a typed inactive PayPal target without a simulator outbox or money write.

## Recorded checks

| Check | Result | Practical limit |
| --- | --- | --- |
| Full unit suite | 112 passed, including 27 PayPal contracts | Synthetic objects and HTTP transports |
| PayPal/PostgreSQL integration | 9 passed | Real migrations, RLS, transactions and API routes; mocked provider responses |
| Simulator approval and repair recovery | 14 passed on stable stack | Local simulator and reference application |
| Operator checks and cooldowns | 3 passed | Local API and PostgreSQL |
| Frontend session regressions | 6 passed | API error/session handling |
| Frontend type check and container build | Passed | Browser usability for real PayPal data still needs acceptance |
| Documentation links / legacy requirement mapping | Passed | Does not close new external-provider or AI gates |

The first simulator regression run overlapped an agent-triggered container
rebuild and failed with interrupted connections. The final run above was performed
after the rebuild completed, with no service changes during the suite; all 14
checks passed. The initial failure is excluded from feature acceptance.

PayPal database checks cover immutable and cross-workspace bindings, current
investigation and repair rejection, concurrent webhook deduplication/conflicts,
signature rejection and verifier outage, transactional rollback, wrong buyer and
unregistered captures, changing orders, expired-lease recovery, an older success
event against a currently refunded capture, and the independent reference target.
They run in new console/reference scratch databases and remove only those
invocation-owned databases after completion. The integration command is now in CI.

## Capability matrix and remaining gates

| Capability | State |
| --- | --- |
| USD, CAPTURE-intent, single-unit PayPal wallet order/capture investigation | Implemented offline |
| Buyer/seller, purchase/order/capture bindings | Verified against synthetic provider contracts |
| App-owned signature postback, durable receipt and replay | Implemented; genuine signed delivery pending |
| Registered-purchase sweep and bounded source reads | Implemented |
| Complete seller inventory, refund/dispute inventory | Unsupported in H2; coverage remains unknown |
| Card-only checkout, multiple purchase units, authorization lifecycle | Unsupported in H2 |
| PayPal access repair or money movement | Disabled / unsupported |
| Bank settlement | Unverified |
| Genuine order, buyer, capture and app-owned webhook acceptance | Pending PayPal account |
| Generative investigation assistant and measured evaluations | H3; not implemented or enabled |

Run `python scripts/check_paypal_contracts.py` with the project's local PostgreSQL
running. Use [PayPal setup](PAYPAL-SETUP.md) for configuration and genuine acceptance,
and the [AI contract](AI-SPEC.md) for the next phase. The default deployment remains
simulator-backed until the explicit PayPal override is configured.
