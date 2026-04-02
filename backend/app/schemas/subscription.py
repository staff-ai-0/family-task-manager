from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    display_name_es: str
    price_monthly_cents: int
    price_annual_cents: int
    limits: dict
    sort_order: int

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

    class Config:
        from_attributes = True


class CheckoutRequest(BaseModel):
    plan_name: str = Field(..., description="Plan name: 'plus' or 'pro'")
    billing_cycle: str = Field(..., description="'monthly' or 'annual'")


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
