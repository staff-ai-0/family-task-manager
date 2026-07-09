"""
Premium gating utilities.

Provides helpers to resolve a family's current plan and enforce feature limits.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.models.family import Family
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import User
from app.services.usage_service import UsageService


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FREE_LIMITS: dict[str, Any] = {
    "max_family_members": 4,
    "max_budget_accounts": 2,
    "max_budget_transactions_per_month": 30,
    "max_recurring_transactions": 0,
    "budget_reports": False,
    "budget_goals": False,
    "csv_import": False,
    "max_receipt_scans_per_month": 0,
    "ai_features": False,
    "max_gigs_per_month": 3,
    "a2a_webhook": False,
    "item_trends": False,
    "fx_cross_charge": False,
    # Family Bank automation (payday allowance, %-split, interest, match).
    # Basic ledger + manual jar transfers stay free; only automation is gated.
    "family_bank_automation": False,
}

# Maps feature name → limit key in the plan's limits dict
FEATURE_LIMIT_MAP: dict[str, str] = {
    # Boolean features
    "budget_reports": "budget_reports",
    "budget_goals": "budget_goals",
    "csv_import": "csv_import",
    "ai_features": "ai_features",
    # Numeric (metered) features
    "budget_transaction": "max_budget_transactions_per_month",
    "recurring_transaction": "max_recurring_transactions",
    "receipt_scan": "max_receipt_scans_per_month",
    "family_member": "max_family_members",
    "budget_account": "max_budget_accounts",
    "gig_completion": "max_gigs_per_month",
    # Scanner v2 boolean features
    "a2a_webhook": "a2a_webhook",
    "item_trends": "item_trends",
    "fx_cross_charge": "fx_cross_charge",
    # Family Bank
    "family_bank_automation": "family_bank_automation",
}

# Tier ordering for plan-rank comparisons. Used by lightweight gates
# (e.g. ``receipt_scanner_service.is_feature_enabled``) that need to ask
# "does this family's plan meet the minimum tier for feature X" without
# raising / metering. The canonical source — do NOT redefine elsewhere.
PLAN_ORDER: dict[str, int] = {"free": 0, "plus": 1, "pro": 2}


# Minimum plan tier required for each feature (omitted → available on free)
FEATURE_MIN_PLAN: dict[str, str] = {
    "budget_reports": "plus",
    "budget_goals": "plus",
    "csv_import": "plus",
    "ai_features": "plus",
    "receipt_scan": "plus",
    "recurring_transaction": "plus",
    # gig_completion available on free with low cap; plus tier raises it
    "gig_completion": "plus",
    # Scanner v2 features
    "a2a_webhook": "plus",
    "item_trends": "plus",
    "fx_cross_charge": "pro",
    # Family Bank automation is a Plus+ upsell (basic ledger stays free).
    "family_bank_automation": "plus",
}


# ---------------------------------------------------------------------------
# FamilyPlan dataclass
# ---------------------------------------------------------------------------

@dataclass
class FamilyPlan:
    """Resolved plan information for a family."""

    name: str
    limits: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    billing_cycle: str | None = None
    family_id: Any = None  # UUID


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------

# Subscription statuses that keep paid entitlements. payment_failed is
# honored only while inside the dunning grace window (see
# _payment_failed_within_grace) — the daily sweep flips grace-expired rows
# to 'grace_expired' which is NOT in this list.
ENTITLED_STATUSES = ("active", "past_due", "payment_failed")


def _payment_failed_within_grace(sub: FamilySubscription) -> bool:
    """True while a payment_failed sub is still inside the grace window.

    payment_failure_at + BILLING_GRACE_DAYS >= now. A missing timestamp is
    treated as within grace (the sweep/webhook will populate or resolve it)
    so a paying customer is never dropped by a bookkeeping gap.
    """
    if sub.payment_failure_at is None:
        return True
    failure_at = sub.payment_failure_at
    if failure_at.tzinfo is None:
        failure_at = failure_at.replace(tzinfo=timezone.utc)
    deadline = failure_at + timedelta(days=settings.BILLING_GRACE_DAYS)
    return datetime.now(timezone.utc) <= deadline


async def _plus_floor_plan(db: AsyncSession, family_id) -> FamilyPlan | None:
    """The Plus ``FamilyPlan`` used as an active-referral-credit floor.

    Any active 'plus' plan row works (limits are identical across a tier's
    currency rows); pick deterministically. Returns None if no active 'plus'
    plan is configured — in which case the caller falls back to free (the
    credit timestamp harmlessly resolves to Plus once a plan exists).
    """
    plus = (
        await db.execute(
            select(SubscriptionPlan)
            .where(
                SubscriptionPlan.name == "plus",
                SubscriptionPlan.is_active == True,  # noqa: E712
            )
            .order_by(SubscriptionPlan.currency)
            .limit(1)
        )
    ).scalar_one_or_none()
    if plus is None:
        return None
    return FamilyPlan(
        name=plus.name,
        limits=plus.limits or {},
        status="active",
        family_id=family_id,
    )


async def get_family_plan_by_id(db: AsyncSession, family_id) -> FamilyPlan:
    """
    Resolve the active plan for a family by id.

    Falls back to the free plan (from DB, then hardcoded defaults).
    """
    # 1. Look for an entitled subscription with plan eager-loaded.
    #    payment_failed counts only while within the dunning grace window.
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == family_id,
                FamilySubscription.status.in_(list(ENTITLED_STATUSES)),
            )
        )
    )
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()

    if (
        subscription
        and subscription.status == "payment_failed"
        and not _payment_failed_within_grace(subscription)
    ):
        # Grace expired but the sweep hasn't run yet — treat as free now.
        subscription = None

    resolved: FamilyPlan | None = None
    if subscription and subscription.plan:
        plan = subscription.plan
        resolved = FamilyPlan(
            name=plan.name,
            limits=plan.limits or {},
            status=subscription.status,
            billing_cycle=subscription.billing_cycle,
            family_id=family_id,
        )

    # 1b. Referral credit floor. An active internal referral credit
    #     (families.referral_bonus_until in the future) entitles the family to
    #     at least Plus, independent of any paid sub. It lives on the family
    #     row so the daily PayPal reconcile sweep never touches it — the credit
    #     cannot be silently erased. A higher paid tier (Pro) always wins.
    bonus_until = (
        await db.execute(
            select(Family.referral_bonus_until).where(Family.id == family_id)
        )
    ).scalar_one_or_none()
    if bonus_until is not None and bonus_until.tzinfo is None:
        bonus_until = bonus_until.replace(tzinfo=timezone.utc)
    bonus_active = (
        bonus_until is not None and bonus_until > datetime.now(timezone.utc)
    )

    if resolved is not None:
        if bonus_active and PLAN_ORDER.get(resolved.name, 0) < PLAN_ORDER["plus"]:
            floor = await _plus_floor_plan(db, family_id)
            if floor is not None:
                return floor
        return resolved

    if bonus_active:
        floor = await _plus_floor_plan(db, family_id)
        if floor is not None:
            return floor

    # 2. No active subscription — try to load the "free" plan from DB.
    #    Plan rows are unique per (name, currency); limits are identical
    #    across a tier's currency rows, so any 'free' row works — pick
    #    deterministically to stay robust if free ever gains currency rows.
    free_query = (
        select(SubscriptionPlan)
        .where(SubscriptionPlan.name == "free")
        .order_by(SubscriptionPlan.currency)
        .limit(1)
    )
    free_result = await db.execute(free_query)
    free_plan = free_result.scalar_one_or_none()

    if free_plan:
        return FamilyPlan(
            name=free_plan.name,
            limits=free_plan.limits or {},
            status="active",
            family_id=family_id,
        )

    # 3. Fallback to hardcoded defaults
    return FamilyPlan(
        name="free",
        limits=dict(DEFAULT_FREE_LIMITS),
        status="active",
        family_id=family_id,
    )


async def get_family_plan(db: AsyncSession, user: User) -> FamilyPlan:
    """Resolve the active plan for the user's family (see get_family_plan_by_id)."""
    return await get_family_plan_by_id(db, user.family_id)


# ---------------------------------------------------------------------------
# Feature gating
# ---------------------------------------------------------------------------

async def require_feature(
    feature: str, db: AsyncSession, user: User, units: int = 1
) -> FamilyPlan:
    """
    Ensure the family's plan allows *feature* for *units* additional usages.

    Returns the FamilyPlan on success, raises HTTP 403 on failure. Pass
    units > 1 when a single API call would consume multiple chargeable
    increments (e.g. a split transaction with N child legs).
    """
    if units < 1:
        raise ValueError("units must be >= 1")

    plan = await get_family_plan(db, user)
    limit_key = FEATURE_LIMIT_MAP.get(feature)

    if limit_key is None:
        # Unknown feature — allow by default (not gated)
        return plan

    limit_value = plan.limits.get(limit_key)

    # If limit key not present in plan, fall back to DEFAULT_FREE_LIMITS
    if limit_value is None:
        limit_value = DEFAULT_FREE_LIMITS.get(limit_key, True)

    plan_needed = FEATURE_MIN_PLAN.get(feature, "plus")

    # Boolean features
    if isinstance(limit_value, bool):
        if limit_value:
            return plan
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "upgrade_required",
                "feature": feature,
                "plan_needed": plan_needed,
                "current_usage": 0,
                "limit": 0,
                "message": f"The '{feature}' feature requires a {plan_needed} plan or higher.",
            },
        )

    # Numeric features
    numeric_limit = int(limit_value)
    if numeric_limit == -1:
        return plan
    if numeric_limit == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "upgrade_required",
                "feature": feature,
                "plan_needed": plan_needed,
                "current_usage": 0,
                "limit": 0,
                "message": f"The '{feature}' feature requires a {plan_needed} plan or higher.",
            },
        )

    # Check metered usage
    family_id = user.family_id
    current_usage = await UsageService.get_usage(db, family_id, feature)
    allowed = current_usage + units <= numeric_limit

    if allowed:
        return plan

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "upgrade_required",
            "feature": feature,
            "plan_needed": plan_needed,
            "current_usage": current_usage,
            "limit": numeric_limit,
            "message": (
                f"You've reached the {feature} limit ({current_usage}/{numeric_limit}). "
                f"Upgrade to {plan_needed} for more."
            ),
        },
    )
