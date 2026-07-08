"""
Subscription-related SQLAlchemy models for premium plan management.

This module contains all models for the subscription system:
- SubscriptionPlan: Available plan tiers (free, premium, etc.)
- FamilySubscription: A family's active subscription
- UsageTracking: Feature usage counters per billing period
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class SubscriptionPlan(Base):
    """Defines available subscription tiers and their limits."""

    __tablename__ = "subscription_plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name_es: Mapped[str] = mapped_column(String(100), nullable=False)
    price_monthly_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_annual_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paypal_plan_id_monthly: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    paypal_plan_id_annual: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships (explicit foreign_keys: family_subscriptions also carries
    # pending_plan_id → subscription_plans for staged plan changes)
    subscriptions: Mapped[list["FamilySubscription"]] = relationship(
        "FamilySubscription",
        back_populates="plan",
        foreign_keys="FamilySubscription.plan_id",
    )


class FamilySubscription(Base):
    """Tracks a family's active subscription to a plan."""

    __tablename__ = "family_subscriptions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    plan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    paypal_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    trial_end_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_failure_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Staged checkout data. When a family with a live (active/past_due/
    # payment_failed) subscription starts an upgrade/downgrade checkout, the
    # new plan + PayPal subscription id are staged here instead of clobbering
    # the live columns. /activate promotes them on payment confirmation and
    # cancels the superseded PayPal subscription. An abandoned checkout
    # leaves the paying subscription untouched.
    pending_plan_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    pending_billing_cycle: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    pending_paypal_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Operator-review flag set by conservative webhook handling (refunds/
    # reversals) — no automatic downgrade, a human decides.
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    review_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships (plan follows plan_id — NOT the staged pending_plan_id)
    plan: Mapped["SubscriptionPlan"] = relationship(
        "SubscriptionPlan",
        back_populates="subscriptions",
        foreign_keys=[plan_id],
    )
    family: Mapped["Family"] = relationship("Family", backref="subscription")


class UsageTracking(Base):
    """Tracks feature usage per family per billing period."""

    __tablename__ = "usage_tracking"
    __table_args__ = (
        UniqueConstraint("family_id", "feature", "period_start", name="uq_usage_family_feature_period"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
