from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, computed_field


class PlanResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    display_name_es: str
    currency: str = "USD"  # ISO 4217 code the price_* fields are denominated in
    price_monthly_cents: int
    price_annual_cents: int
    limits: dict
    sort_order: int
    # Raw PayPal plan ids are pulled from the ORM row but never serialized —
    # they only feed the checkout_ready_* flags below, which let the pricing
    # UI hide/disable upgrade buttons for rows the operator has not wired to
    # PayPal yet (e.g. migration-seeded MXN rows awaiting provisioning).
    paypal_plan_id_monthly: Optional[str] = Field(None, exclude=True)
    paypal_plan_id_annual: Optional[str] = Field(None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checkout_ready_monthly(self) -> bool:
        """True when this row can actually be checked out monthly."""
        return bool(self.paypal_plan_id_monthly)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checkout_ready_annual(self) -> bool:
        """True when this row can actually be checked out annually."""
        return bool(self.paypal_plan_id_annual)

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    id: UUID
    plan: PlanResponse
    billing_cycle: str
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancel_at_period_end: bool = False
    trial_end_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CheckoutRequest(BaseModel):
    plan_name: str = Field(..., description="Plan name: 'plus' or 'pro'")
    billing_cycle: str = Field(..., description="'monthly' or 'annual'")
    currency: Optional[str] = Field(
        None,
        min_length=3,
        max_length=3,
        description=(
            "ISO 4217 currency of the plan row to check out ('MXN' or 'USD'). "
            "Omitted → MXN preferred (Mexico-first), falling back to any "
            "single active row for the tier."
        ),
    )


class CheckoutResponse(BaseModel):
    approval_url: str
    paypal_subscription_id: str


class ActivateRequest(BaseModel):
    paypal_subscription_id: str


class UsageResponse(BaseModel):
    feature: str
    current: int
    limit: int  # -1 = unlimited, 0 = disabled
    period: str  # YYYY-MM-DD
