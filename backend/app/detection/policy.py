"""Phase 0 contract for one-time access eligibility; no I/O or execution authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


POLICY_VERSION = "one_time_access_v1"


class Environment(StrEnum):
    SIMULATED = "simulated"
    TEST = "test"
    LIVE = "live"


class PaymentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    PROCESSING = "processing"
    REQUIRES_ACTION = "requires_action"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    REQUIRES_CAPTURE = "requires_capture"
    CANCELED = "canceled"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AccessStatus(StrEnum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    UNKNOWN = "unknown"


class Outcome(StrEnum):
    ELIGIBLE = "eligible"
    PENDING = "pending"
    HEALTHY = "healthy"
    BLOCKED = "blocked"
    AWAITING_EVIDENCE = "awaiting_evidence"
    MANUAL_REVIEW = "manual_review"
    OPERATION_IN_PROGRESS = "operation_in_progress"


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Identifiers must be nonempty strings without outer whitespace")


def _minor_units(value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("Amounts and counts must be nonnegative integers")


def _currency(value: str) -> None:
    if not isinstance(value, str) or len(value) != 3 or not all("a" <= c <= "z" for c in value):
        raise ValueError("Currency must be three lowercase ASCII letters")


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware")


def _boolean(value: bool) -> None:
    if type(value) is not bool:
        raise ValueError("Flags must be explicit booleans")


@dataclass(frozen=True)
class ProviderScope:
    workspace_id: str
    connection_id: str
    account_id: str
    environment: Environment

    def __post_init__(self) -> None:
        for value in (self.workspace_id, self.connection_id, self.account_id):
            _identifier(value)
        if not isinstance(self.environment, Environment):
            raise ValueError("Environment must be normalized explicitly")


@dataclass(frozen=True)
class AccessBinding:
    workspace_id: str
    purchase_id: str
    customer_id: str
    product_id: str

    def __post_init__(self) -> None:
        for value in (self.workspace_id, self.purchase_id, self.customer_id, self.product_id):
            _identifier(value)


@dataclass(frozen=True)
class Purchase:
    binding: AccessBinding
    provider_scope: ProviderScope
    provider_customer_id: str
    payment_intent_ids: tuple[str, ...]
    expected_amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        _identifier(self.provider_customer_id)
        _minor_units(self.expected_amount_minor)
        _currency(self.currency)
        if self.binding.workspace_id != self.provider_scope.workspace_id:
            raise ValueError("Purchase and connection must belong to one workspace")
        if type(self.payment_intent_ids) is not tuple:
            raise ValueError("Payment attempt identifiers must be an immutable tuple")
        for value in self.payment_intent_ids:
            _identifier(value)
        if len(set(self.payment_intent_ids)) != len(self.payment_intent_ids):
            raise ValueError("Registered payment attempt identifiers must be unique")


@dataclass(frozen=True)
class EvidenceWindow:
    started_at: datetime
    completed_at: datetime
    complete: bool

    def __post_init__(self) -> None:
        _aware(self.started_at)
        _aware(self.completed_at)
        _boolean(self.complete)
        if self.completed_at < self.started_at:
            raise ValueError("An observation cannot finish before it starts")


@dataclass(frozen=True)
class PaymentEvidence:
    scope: ProviderScope
    payment_intent_id: str
    provider_customer_id: str
    status: PaymentStatus
    amount_received_minor: int
    currency: str
    successful_attempt_ids: tuple[str, ...]
    refund_count: int
    dispute_count: int
    payment_window: EvidenceWindow
    reversal_window: EvidenceWindow
    first_confirmed_succeeded_at: datetime | None

    def __post_init__(self) -> None:
        _identifier(self.payment_intent_id)
        _identifier(self.provider_customer_id)
        _minor_units(self.amount_received_minor)
        _currency(self.currency)
        _minor_units(self.refund_count)
        _minor_units(self.dispute_count)
        if not isinstance(self.status, PaymentStatus):
            raise ValueError("Payment status must be normalized explicitly")
        if type(self.successful_attempt_ids) is not tuple:
            raise ValueError("Successful attempt identifiers must be an immutable tuple")
        for value in self.successful_attempt_ids:
            _identifier(value)
        if len(set(self.successful_attempt_ids)) != len(self.successful_attempt_ids):
            raise ValueError("Successful attempt identifiers must be unique")
        if self.first_confirmed_succeeded_at is not None:
            _aware(self.first_confirmed_succeeded_at)


@dataclass(frozen=True)
class AccessEvidence:
    binding: AccessBinding
    status: AccessStatus
    revision: int
    ever_activated: bool
    window: EvidenceWindow

    def __post_init__(self) -> None:
        _minor_units(self.revision)
        _boolean(self.ever_activated)
        if not isinstance(self.status, AccessStatus):
            raise ValueError("Access status must be normalized explicitly")


@dataclass(frozen=True)
class PolicyConfig:
    grace_period: timedelta = timedelta(seconds=120)
    max_evidence_age: timedelta = timedelta(seconds=60)

    def __post_init__(self) -> None:
        if self.grace_period < timedelta(0) or self.max_evidence_age <= timedelta(0):
            raise ValueError("Grace must be nonnegative and freshness must be positive")


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: tuple[str, ...]
    policy_version: str = POLICY_VERSION


def evaluate_access(
    purchase: Purchase,
    payment: PaymentEvidence | None,
    access: AccessEvidence | None,
    *,
    now: datetime,
    active_operation: bool = False,
    config: PolicyConfig = PolicyConfig(),
) -> Decision:
    """Evaluate a proposal candidate. Authorization/approval/dispatch are separate gates.

    A complete payment window covers every registered attempt. A complete reversal
    window covers relevant charges and all refund/dispute pages. Adapters must not
    turn failed or partial reads into complete empty results. Financial settlement
    is deliberately absent from this core access predicate.
    """
    _aware(now)
    _boolean(active_operation)
    if purchase.provider_scope.environment is Environment.LIVE:
        return Decision(Outcome.BLOCKED, ("live_environment_unsupported",))
    if purchase.expected_amount_minor == 0:
        return Decision(Outcome.BLOCKED, ("zero_price_unsupported",))
    if payment is None or access is None:
        return Decision(Outcome.AWAITING_EVIDENCE, ("missing_observation",))

    scope_errors = []
    if payment.scope != purchase.provider_scope:
        scope_errors.append("provider_scope_mismatch")
    if payment.payment_intent_id not in purchase.payment_intent_ids:
        scope_errors.append("unregistered_payment_attempt")
    if payment.provider_customer_id != purchase.provider_customer_id:
        scope_errors.append("provider_customer_mismatch")
    if access.binding != purchase.binding:
        scope_errors.append("access_binding_mismatch")
    if not set(payment.successful_attempt_ids).issubset(purchase.payment_intent_ids):
        scope_errors.append("unregistered_successful_attempt")
    if scope_errors:
        return Decision(Outcome.AWAITING_EVIDENCE, tuple(scope_errors))

    evidence_errors = []
    for name, window in (
        ("payment", payment.payment_window),
        ("reversal", payment.reversal_window),
        ("access", access.window),
    ):
        if not window.complete:
            evidence_errors.append(f"{name}_incomplete")
        if window.completed_at > now:
            evidence_errors.append(f"{name}_future_observation")
        elif now - window.started_at > config.max_evidence_age:
            evidence_errors.append(f"{name}_stale")
    if evidence_errors:
        return Decision(Outcome.AWAITING_EVIDENCE, tuple(evidence_errors))

    review_reasons = []
    if payment.refund_count:
        review_reasons.append("refund_history")
    if payment.dispute_count:
        review_reasons.append("dispute_history")
    if len(payment.successful_attempt_ids) > 1:
        review_reasons.append("multiple_successful_attempts")
    if review_reasons:
        return Decision(Outcome.MANUAL_REVIEW, tuple(review_reasons))

    if payment.status is PaymentStatus.UNKNOWN or access.status is AccessStatus.UNKNOWN:
        return Decision(Outcome.AWAITING_EVIDENCE, ("unknown_state",))
    selected_succeeded = payment.payment_intent_id in payment.successful_attempt_ids
    if selected_succeeded != (payment.status is PaymentStatus.SUCCEEDED):
        return Decision(Outcome.AWAITING_EVIDENCE, ("inconsistent_attempt_evidence",))
    if payment.status in (PaymentStatus.FAILED, PaymentStatus.CANCELED):
        return Decision(Outcome.BLOCKED, ("payment_not_successful",))
    if payment.status is not PaymentStatus.SUCCEEDED:
        return Decision(Outcome.PENDING, ("payment_not_successful",))
    if payment.currency != purchase.currency or payment.amount_received_minor != purchase.expected_amount_minor:
        return Decision(Outcome.MANUAL_REVIEW, ("payment_value_mismatch",))
    if access.status in (AccessStatus.SUSPENDED, AccessStatus.REVOKED):
        return Decision(Outcome.BLOCKED, ("intentional_access_block",))
    if access.status is AccessStatus.ACTIVE:
        return Decision(Outcome.HEALTHY, ("access_already_active",))
    if access.ever_activated:
        return Decision(Outcome.BLOCKED, ("previously_activated_access",))
    first_success = payment.first_confirmed_succeeded_at
    if first_success is None or first_success > payment.payment_window.completed_at:
        return Decision(Outcome.AWAITING_EVIDENCE, ("invalid_success_confirmation_time",))
    if now - first_success < config.grace_period:
        return Decision(Outcome.PENDING, ("fulfillment_grace_period",))
    if active_operation:
        return Decision(Outcome.OPERATION_IN_PROGRESS, ("existing_active_or_unknown_operation",))
    return Decision(Outcome.ELIGIBLE, ("paid_access_missing",))
