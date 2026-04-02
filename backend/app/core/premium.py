"""
Premium gating utilities.

Provides helpers to resolve a family's current plan and enforce feature limits.
"""
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
}

# Minimum plan tier required for each feature (omitted → available on free)
FEATURE_MIN_PLAN: dict[str, str] = {
    "budget_reports": "plus",
    "budget_goals": "plus",
    "csv_import": "plus",
    "ai_features": "plus",
    "receipt_scan": "plus",
    "recurring_transaction": "plus",
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

async def get_family_plan(db: AsyncSession, user: User) -> FamilyPlan:
    """
    Resolve the active plan for the user's family.

    Falls back to the free plan (from DB, then hardcoded defaults).
    """
    family_id = user.family_id

    # 1. Look for an active (or past_due) subscription with plan eager-loaded
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == family_id,
                FamilySubscription.status.in_(["active", "past_due"]),
            )
        )
    )
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()

    if subscription and subscription.plan:
        plan = subscription.plan
        return FamilyPlan(
            name=plan.name,
            limits=plan.limits or {},
            status=subscription.status,
            billing_cycle=subscription.billing_cycle,
            family_id=family_id,
        )

    # 2. No active subscription — try to load the "free" plan from DB
    free_query = select(SubscriptionPlan).where(SubscriptionPlan.name == "free")
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


# ---------------------------------------------------------------------------
# Feature gating
# ---------------------------------------------------------------------------

async def require_feature(
    feature: str, db: AsyncSession, user: User
) -> FamilyPlan:
    """
    Ensure the family's plan allows *feature*.

    Returns the FamilyPlan on success, raises HTTP 403 on failure.
    """
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
    allowed = current_usage < numeric_limit

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
