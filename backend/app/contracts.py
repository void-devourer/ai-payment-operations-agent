"""Strict request contracts shared across independently deployed services."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_:.-]*$")]
Amount = Annotated[int, Field(strict=True, ge=1, le=10**12)]
Revision = Annotated[int, Field(strict=True, ge=0)]
Currency = Annotated[str, Field(strict=True, pattern=r"^[a-z]{3}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PurchaseRegistration(Contract):
    contract_version: Literal["purchase_v1"] = "purchase_v1"
    workspace_id: Identifier
    purchase_id: Identifier
    customer_id: Identifier
    product_id: Literal["digital_pass"]
    expected_access: Literal["digital_pass"] = "digital_pass"
    expected_amount_minor: Amount
    currency: Currency
    connection_id: Identifier
    provider_customer_id: Identifier


class AttemptRegistration(Contract):
    payment_intent_id: Identifier


class Checkout(Contract):
    purchase_id: Identifier
    customer_id: Identifier
    product_id: Literal["digital_pass"] = "digital_pass"
    fault_mode: Literal["none", "pause_fulfillment"] = "none"


class SimulatedPayment(Contract):
    purchase_id: Identifier
    customer_id: Identifier
    amount_minor: Amount
    currency: Currency


class Grant(Contract):
    contract_version: Literal["access_grant_v1"] = "access_grant_v1"
    operation_id: Identifier
    workspace_id: Identifier
    purchase_id: Identifier
    customer_id: Identifier
    product_id: Literal["digital_pass"]
    expected_revision: Revision
    expected_status: Literal["inactive"] = "inactive"
    proposal_id: Identifier
    policy_version: Literal["one_time_access_v1"] = "one_time_access_v1"
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value):
        if value.utcoffset() is None:
            raise ValueError("Expiry must include a timezone")
        return value.astimezone(UTC)
