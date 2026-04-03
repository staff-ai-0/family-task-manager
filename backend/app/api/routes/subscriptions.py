"""
Subscription management API endpoints.

Provides plan listing, current subscription info, usage tracking,
checkout initiation, and cancellation.
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.premium import get_family_plan, FEATURE_LIMIT_MAP, DEFAULT_FREE_LIMITS
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import User
from app.schemas.subscription import (
    CheckoutRequest,
    CheckoutResponse,
    PlanResponse,
    SubscriptionResponse,
    UsageResponse,
)
from app.services.usage_service import UsageService
from app.services.paypal_service import PayPalService

router = APIRouter()


@router.get("/plans", response_model=List[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    """List all active subscription plans ordered by sort_order."""
    query = (
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)  # noqa: E712
        .order_by(SubscriptionPlan.sort_order)
    )
    result = await db.execute(query)
    plans = result.scalars().all()
    return plans


@router.get("/current", response_model=SubscriptionResponse | dict)
async def get_current_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """Get the family's current subscription details."""
    family_plan = await get_family_plan(db, current_user)

    # Try to find the actual FamilySubscription record with plan eager-loaded
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == current_user.family_id,
                FamilySubscription.status.in_(["active", "past_due"]),
            )
        )
    )
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()

    if subscription:
        return subscription

    # No active subscription — return a default free response
    return {
        "plan_name": "free",
        "status": "active",
        "limits": family_plan.limits,
    }


@router.get("/usage", response_model=List[UsageResponse])
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """Get current month's usage for all numeric (metered) features."""
    family_plan = await get_family_plan(db, current_user)
    period = UsageService._current_period()
    usage_list = []

    for feature, limit_key in FEATURE_LIMIT_MAP.items():
        limit_value = family_plan.limits.get(limit_key)
        if limit_value is None:
            limit_value = DEFAULT_FREE_LIMITS.get(limit_key, 0)

        # Skip boolean features — only report numeric ones
        if isinstance(limit_value, bool):
            continue

        current = await UsageService.get_usage(
            db, current_user.family_id, feature, period
        )
        usage_list.append(
            UsageResponse(
                feature=feature,
                current=current,
                limit=int(limit_value),
                period=str(period),
            )
        )

    return usage_list


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """Create a PayPal subscription checkout session."""
    # Validate plan exists
    query = select(SubscriptionPlan).where(
        and_(
            SubscriptionPlan.name == request.plan_name,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )
    result = await db.execute(query)
    plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{request.plan_name}' not found",
        )

    # Get PayPal plan ID for this plan and billing cycle
    if request.billing_cycle == "monthly":
        paypal_plan_id = plan.paypal_plan_id_monthly
    elif request.billing_cycle == "annual":
        paypal_plan_id = plan.paypal_plan_id_annual
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid billing_cycle. Use 'monthly' or 'annual'",
        )

    if not paypal_plan_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"PayPal plan not configured for {plan.name} {request.billing_cycle} billing",
        )

    # Create PayPal subscription
    try:
        paypal_service = PayPalService()
        result = paypal_service.create_subscription(
            plan_id=paypal_plan_id,
            return_url=f"{current_user.family_id}/subscription/success",  # Will be handled by frontend
            cancel_url=f"{current_user.family_id}/subscription/cancel",  # Will be handled by frontend
        )

        if not result.get("approval_url"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create PayPal subscription",
            )

        return CheckoutResponse(
            approval_url=result["approval_url"],
            paypal_subscription_id=result["subscription_id"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PayPal error: {str(e)}",
        )


@router.post("/activate")
async def activate_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """
    Activate a subscription after PayPal approval.

    Called after user approves payment on PayPal and returns to our app.
    The token should be in the URL query params (PayPal returns it).
    """
    # For now, this is a placeholder
    # In production, you'd:
    # 1. Get the token from query params
    # 2. Execute the billing agreement
    # 3. Create FamilySubscription record
    # 4. Activate the subscription

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Subscription activation endpoint - frontend will handle PayPal return",
    )


@router.post("/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """Cancel the family's active subscription."""
    query = select(FamilySubscription).where(
        and_(
            FamilySubscription.family_id == current_user.family_id,
            FamilySubscription.status.in_(["active", "past_due"]),
        )
    )
    result = await db.execute(query)
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )

    subscription.status = "cancelled"
    subscription.cancelled_at = datetime.now(timezone.utc)
    await db.commit()

    return {"status": "cancelled", "cancelled_at": str(subscription.cancelled_at)}
