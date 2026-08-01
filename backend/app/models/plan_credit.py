"""Coupons and the unified plan-credit grant.

Two tables, one mechanism:

- ``Coupon`` — an operator-authored code. Cross-tenant by design (it is a
  catalog, like subscription_plans), so it carries no family_id and every
  read/write goes through require_superadmin. The one exception is the
  redeem path, which looks a single code up by exact match and never lists.

- ``PlanCreditGrant`` — one row per credit window actually given to a family.
  This is THE credit mechanism: coupon redemptions, referral rewards and
  operator comps all write it, and premium.get_family_plan_by_id resolves a
  tier floor from it. It replaced families.referral_bonus_until, which was a
  single Plus-only timestamp with no tier, no lifetime, no revoke and no
  per-grant audit trail.

Credit is INTERNAL: no PayPal object is created and no PayPal-linked column
is ever written, so the nightly reconcile sweep (which overwrites
current_period_end from PayPal's next_billing_at) cannot erase it.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# Where a grant came from. Closed vocabulary — a new source means new
# resolution semantics, which is a code change, not a data value.
CREDIT_SOURCES = ("coupon", "referral", "operator")

# Coupon kinds carry NO behavior. launch/beta/comp share one mechanic —
# "N days (or forever) at tier T" — and exist so an operator can filter
# "show me every beta-tester family" and separate a launch promo from a
# friends-and-family comp in reporting. Never branch resolution logic on
# kind; if a real behavioral difference appears, model it as a column.
COUPON_KINDS = ("launch", "beta", "comp")


class Coupon(Base):
    """An operator-authored redeemable code."""

    __tablename__ = "coupons"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    # Stored upper-case; CouponService.normalize_code is the only writer.
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # The tier the credit floors the family at (plus | pro).
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    # NULL => lifetime.
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # NULL => unlimited redemptions.
    max_redemptions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Denormalized counter for display AND for the race-free cap check (see
    # CouponService.redeem). The authoritative count is
    # count(plan_credit_grants WHERE coupon_id = id) — the admin redemption
    # list reads that, so a drifted counter is visible rather than trusted.
    redemption_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    campaign: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 2 (percent/amount off a recurring PayPal charge). Reserved so the
    # schema does not churn when it lands; NOTHING reads these today.
    discount_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount_amount_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discount_cycles: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlanCreditGrant(Base):
    """One credit window granted to one family."""

    __tablename__ = "plan_credit_grants"
    __table_args__ = (
        # THE anti-double-redeem guard: a family holds at most one grant per
        # coupon. Postgres treats NULLs as distinct, so this does not
        # constrain referral/operator grants (coupon_id IS NULL) — correct, a
        # family may legitimately hold many of those.
        UniqueConstraint(
            "family_id", "coupon_id", name="uq_plan_credit_grants_family_coupon"
        ),
        # Resolution query: active grants for one family, on every plan
        # resolution. Partial so revoked history stays out of the index.
        Index(
            "ix_plan_credit_grants_family_live",
            "family_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    coupon_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("coupons.id", ondelete="SET NULL"), nullable=True
    )
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # NULL => lifetime.
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft revoke — preserves the audit trail. Never DELETE a grant.
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by_user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
