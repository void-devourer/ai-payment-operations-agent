"""Executable Phase 0 policy scenarios; no external services or dependencies."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
import unittest

from backend.app.detection.policy import (
    POLICY_VERSION,
    AccessBinding,
    AccessEvidence,
    AccessStatus,
    Environment,
    EvidenceWindow,
    Outcome,
    PaymentEvidence,
    PaymentStatus,
    PolicyConfig,
    ProviderScope,
    Purchase,
    evaluate_access,
)


class AccessPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 12, tzinfo=UTC)
        self.scope = ProviderScope("ws_a", "conn_a", "acct_test_a", Environment.SIMULATED)
        self.binding = AccessBinding("ws_a", "purchase_a", "customer_a", "product_a")
        self.purchase = Purchase(self.binding, self.scope, "cus_a", ("pi_a",), 2500, "usd")
        self.window = EvidenceWindow(self.now - timedelta(seconds=2), self.now, True)
        self.payment = PaymentEvidence(
            self.scope, "pi_a", "cus_a", PaymentStatus.SUCCEEDED, 2500, "usd",
            ("pi_a",), 0, 0, self.window, self.window,
            self.now - timedelta(seconds=120),
        )
        self.access = AccessEvidence(self.binding, AccessStatus.INACTIVE, 0, False, self.window)

    def decision(self, *, purchase=None, payment=None, access=None, **kwargs):
        return evaluate_access(
            purchase or self.purchase, payment or self.payment, access or self.access,
            now=self.now, **kwargs,
        )

    def test_overdue_paid_missing_access_is_a_versioned_candidate(self):
        result = self.decision()
        self.assertEqual(result.outcome, Outcome.ELIGIBLE)
        self.assertEqual(result.policy_version, POLICY_VERSION)
        self.assertEqual(result.reasons, ("paid_access_missing",))

    def test_grace_period_boundary(self):
        for elapsed, expected in ((119, Outcome.PENDING), (120, Outcome.ELIGIBLE), (121, Outcome.ELIGIBLE)):
            with self.subTest(elapsed=elapsed):
                evidence = replace(self.payment, first_confirmed_succeeded_at=self.now - timedelta(seconds=elapsed))
                self.assertEqual(self.decision(payment=evidence).outcome, expected)

    def test_already_active_requires_no_grant(self):
        active = replace(self.access, status=AccessStatus.ACTIVE, ever_activated=True)
        self.assertEqual(self.decision(access=active).outcome, Outcome.HEALTHY)

    def test_refund_or_dispute_on_active_access_remains_review(self):
        active = replace(self.access, status=AccessStatus.ACTIVE, ever_activated=True)
        for fields, reason in (({"refund_count": 1}, "refund_history"), ({"dispute_count": 1}, "dispute_history")):
            with self.subTest(reason=reason):
                result = self.decision(payment=replace(self.payment, **fields), access=active)
                self.assertEqual(result.outcome, Outcome.MANUAL_REVIEW)
                self.assertIn(reason, result.reasons)

    def test_any_reversal_history_blocks_missing_access_grant(self):
        for refund_count, dispute_count in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(refunds=refund_count, disputes=dispute_count):
                result = self.decision(payment=replace(self.payment, refund_count=refund_count, dispute_count=dispute_count))
                self.assertEqual(result.outcome, Outcome.MANUAL_REVIEW)

    def test_incomplete_bundle_never_means_empty_history(self):
        for field in ("payment_window", "reversal_window"):
            with self.subTest(field=field):
                result = self.decision(payment=replace(self.payment, **{field: replace(self.window, complete=False)}))
                self.assertEqual(result.outcome, Outcome.AWAITING_EVIDENCE)
        self.assertEqual(self.decision(access=replace(self.access, window=replace(self.window, complete=False))).outcome, Outcome.AWAITING_EVIDENCE)

    def test_freshness_uses_oldest_read_in_bundle(self):
        for age, expected in ((60, Outcome.ELIGIBLE), (61, Outcome.AWAITING_EVIDENCE)):
            with self.subTest(age=age):
                window = replace(self.window, started_at=self.now - timedelta(seconds=age))
                self.assertEqual(self.decision(payment=replace(self.payment, reversal_window=window)).outcome, expected)

    def test_each_bundle_can_be_stale(self):
        stale = EvidenceWindow(self.now - timedelta(seconds=62), self.now - timedelta(seconds=61), True)
        for field in ("payment_window", "reversal_window"):
            with self.subTest(field=field):
                self.assertEqual(self.decision(payment=replace(self.payment, **{field: stale})).outcome, Outcome.AWAITING_EVIDENCE)
        self.assertEqual(self.decision(access=replace(self.access, window=stale)).outcome, Outcome.AWAITING_EVIDENCE)

    def test_future_observations_are_not_fresh(self):
        future = EvidenceWindow(self.now, self.now + timedelta(seconds=1), True)
        self.assertEqual(self.decision(payment=replace(self.payment, payment_window=future)).outcome, Outcome.AWAITING_EVIDENCE)

    def test_missing_observations_block(self):
        for payment, access in ((None, self.access), (self.payment, None), (None, None)):
            with self.subTest(payment=payment is None, access=access is None):
                result = evaluate_access(self.purchase, payment, access, now=self.now)
                self.assertEqual(result.outcome, Outcome.AWAITING_EVIDENCE)

    def test_every_provider_scope_component_must_match(self):
        for fields in ({"workspace_id": "ws_b"}, {"connection_id": "conn_b"}, {"account_id": "acct_b"}, {"environment": Environment.TEST}):
            with self.subTest(fields=fields):
                result = self.decision(payment=replace(self.payment, scope=replace(self.scope, **fields)))
                self.assertEqual(result.outcome, Outcome.AWAITING_EVIDENCE)

    def test_every_access_binding_component_must_match(self):
        for field in ("workspace_id", "purchase_id", "customer_id", "product_id"):
            with self.subTest(field=field):
                access = replace(self.access, binding=replace(self.binding, **{field: "other"}))
                self.assertEqual(self.decision(access=access).outcome, Outcome.AWAITING_EVIDENCE)

    def test_provider_customer_and_attempt_are_exact(self):
        for fields in ({"provider_customer_id": "cus_other"}, {"payment_intent_id": "pi_other"}, {"successful_attempt_ids": ("pi_other",)}):
            with self.subTest(fields=fields):
                self.assertEqual(self.decision(payment=replace(self.payment, **fields)).outcome, Outcome.AWAITING_EVIDENCE)

    def test_two_successful_registered_attempts_require_review(self):
        purchase = replace(self.purchase, payment_intent_ids=("pi_a", "pi_b"))
        result = self.decision(purchase=purchase, payment=replace(self.payment, successful_attempt_ids=("pi_a", "pi_b")))
        self.assertEqual(result.outcome, Outcome.MANUAL_REVIEW)

    def test_equal_value_distinct_purchases_are_independent(self):
        binding = replace(self.binding, purchase_id="purchase_b")
        purchase = replace(self.purchase, binding=binding, payment_intent_ids=("pi_b",))
        payment = replace(self.payment, payment_intent_id="pi_b", successful_attempt_ids=("pi_b",))
        access = replace(self.access, binding=binding)
        self.assertEqual(self.decision().outcome, Outcome.ELIGIBLE)
        self.assertEqual(self.decision(purchase=purchase, payment=payment, access=access).outcome, Outcome.ELIGIBLE)

    def test_non_success_states_never_qualify(self):
        for status in PaymentStatus:
            if status is PaymentStatus.SUCCEEDED:
                continue
            with self.subTest(status=status):
                result = self.decision(payment=replace(self.payment, status=status, successful_attempt_ids=()))
                self.assertNotEqual(result.outcome, Outcome.ELIGIBLE)

    def test_inconsistent_success_observations_are_uncertain(self):
        result = self.decision(payment=replace(self.payment, successful_attempt_ids=()))
        self.assertEqual(result.outcome, Outcome.AWAITING_EVIDENCE)
        result = self.decision(payment=replace(self.payment, status=PaymentStatus.PROCESSING))
        self.assertEqual(result.outcome, Outcome.AWAITING_EVIDENCE)

    def test_wrong_amount_or_currency_requires_review(self):
        for fields in ({"amount_received_minor": 2499}, {"amount_received_minor": 2501}, {"currency": "eur"}):
            with self.subTest(fields=fields):
                self.assertEqual(self.decision(payment=replace(self.payment, **fields)).outcome, Outcome.MANUAL_REVIEW)

    def test_zero_price_is_unsupported(self):
        self.assertEqual(self.decision(purchase=replace(self.purchase, expected_amount_minor=0)).outcome, Outcome.BLOCKED)

    def test_intentional_blocks_and_previous_activation_never_reinstate(self):
        for status in (AccessStatus.SUSPENDED, AccessStatus.REVOKED):
            with self.subTest(status=status):
                self.assertEqual(self.decision(access=replace(self.access, status=status, ever_activated=True)).outcome, Outcome.BLOCKED)
        self.assertEqual(self.decision(access=replace(self.access, ever_activated=True)).outcome, Outcome.BLOCKED)

    def test_unknown_access_is_uncertain(self):
        self.assertEqual(self.decision(access=replace(self.access, status=AccessStatus.UNKNOWN)).outcome, Outcome.AWAITING_EVIDENCE)

    def test_existing_or_unknown_operation_blocks_new_proposal(self):
        self.assertEqual(self.decision(active_operation=True).outcome, Outcome.OPERATION_IN_PROGRESS)

    def test_missing_or_future_first_confirmation_is_uncertain(self):
        for first_success in (None, self.now + timedelta(seconds=1)):
            with self.subTest(first_success=first_success):
                self.assertEqual(self.decision(payment=replace(self.payment, first_confirmed_succeeded_at=first_success)).outcome, Outcome.AWAITING_EVIDENCE)

    def test_live_environment_is_not_enabled_by_matching_scope(self):
        scope = replace(self.scope, environment=Environment.LIVE)
        result = self.decision(purchase=replace(self.purchase, provider_scope=scope), payment=replace(self.payment, scope=scope))
        self.assertEqual(result.outcome, Outcome.BLOCKED)

    def test_matching_test_environment_can_qualify(self):
        scope = replace(self.scope, environment=Environment.TEST)
        result = self.decision(purchase=replace(self.purchase, provider_scope=scope), payment=replace(self.payment, scope=scope))
        self.assertEqual(result.outcome, Outcome.ELIGIBLE)

    def test_timezone_equivalence_preserves_boundary(self):
        first_success = self.payment.first_confirmed_succeeded_at.astimezone(timezone(timedelta(hours=5, minutes=30)))
        self.assertEqual(self.decision(payment=replace(self.payment, first_confirmed_succeeded_at=first_success)).outcome, Outcome.ELIGIBLE)

    def test_invalid_money_and_counts_reject_float_bool_and_negative(self):
        for value in (2500.0, True, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    replace(self.purchase, expected_amount_minor=value)
                with self.assertRaises(ValueError):
                    replace(self.payment, refund_count=value)

    def test_currency_and_identifiers_are_not_silently_normalized(self):
        for currency in ("USD", "us", "us1", "üsd"):
            with self.subTest(currency=currency), self.assertRaises(ValueError):
                replace(self.purchase, currency=currency)
        with self.assertRaises(ValueError):
            replace(self.binding, customer_id=" customer_a")

    def test_timestamps_must_be_aware_and_ordered(self):
        with self.assertRaises(ValueError):
            replace(self.window, completed_at=self.now.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            replace(self.window, started_at=self.now + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            evaluate_access(self.purchase, self.payment, self.access, now=self.now.replace(tzinfo=None))

    def test_config_and_flags_are_explicit(self):
        with self.assertRaises(ValueError):
            PolicyConfig(grace_period=timedelta(seconds=-1))
        with self.assertRaises(ValueError):
            PolicyConfig(max_evidence_age=timedelta(0))
        with self.assertRaises(ValueError):
            replace(self.window, complete="true")
        with self.assertRaises(ValueError):
            self.decision(active_operation="false")

    def test_attempt_collections_are_immutable_and_unique(self):
        for value in (["pi_a"], ("pi_a", "pi_a")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(self.purchase, payment_intent_ids=value)


if __name__ == "__main__":
    unittest.main()
