"""
Subscription management API endpoints.

Provides plan listing, current subscription info, usage tracking,
checkout initiation, and cancellation.
"""

import asyncio
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
    ActivateRequest,
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
    from app.core.premium import ENTITLED_STATUSES, _payment_failed_within_grace

    family_plan = await get_family_plan(db, current_user)

    # Try to find the actual FamilySubscription record with plan eager-loaded.
    # payment_failed is included while inside the dunning grace window so the
    # UI can show the sub (and its payment problem) instead of "free".
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == current_user.family_id,
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
        subscription = None

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
    """Create a PayPal subscription checkout session and persist a pending row."""
    from app.core.config import settings

    query = select(SubscriptionPlan).where(
        and_(
            SubscriptionPlan.name == request.plan_name,
            SubscriptionPlan.is_active == True,  # noqa: E712
        )
    )
    plan = (await db.execute(query)).scalar_one_or_none()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{request.plan_name}' not found",
        )

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
            detail=f"PayPal plan not configured for {plan.name} {request.billing_cycle}",
        )

    public_url = (settings.PUBLIC_URL or settings.BASE_URL).rstrip("/")
    return_url = f"{public_url}/parent/settings/subscription/activate"
    cancel_url = f"{public_url}/parent/settings/subscription?cancelled=1"

    try:
        paypal_service = PayPalService()
        result = await asyncio.to_thread(
            paypal_service.create_subscription,
            plan_id=paypal_plan_id,
            return_url=return_url,
            cancel_url=cancel_url,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"PayPal error: {str(e)}",
        )

    if not result.get("approval_url"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create PayPal subscription",
        )

    # Persist checkout state so /activate can resolve plan/cycle from
    # paypal_subscription_id. The family_id column is unique — one
    # FamilySubscription per family.
    #
    # CRITICAL guard: when the family already has a LIVE subscription
    # (active / past_due / payment_failed-in-grace), we must NOT mutate the
    # live row — an abandoned checkout would otherwise downgrade a paying
    # customer to free and orphan their PayPal subscription (double
    # billing). Instead the new checkout is STAGED in the pending_* columns
    # and promoted by /activate (or the ACTIVATED webhook) only after
    # payment confirmation, which also cancels the superseded PayPal sub.
    from app.core.premium import ENTITLED_STATUSES

    existing = await db.execute(
        select(FamilySubscription).where(
            FamilySubscription.family_id == current_user.family_id
        )
    )
    row = existing.scalar_one_or_none()
    if row and row.status in ENTITLED_STATUSES:
        row.pending_plan_id = plan.id
        row.pending_billing_cycle = request.billing_cycle
        row.pending_paypal_subscription_id = result["subscription_id"]
    elif row:
        # Row exists but is not a live entitlement (pending / cancelled /
        # expired / grace_expired) — safe to refresh in place.
        row.plan_id = plan.id
        row.billing_cycle = request.billing_cycle
        row.status = "pending"
        row.paypal_subscription_id = result["subscription_id"]
        row.pending_plan_id = None
        row.pending_billing_cycle = None
        row.pending_paypal_subscription_id = None
    else:
        row = FamilySubscription(
            family_id=current_user.family_id,
            plan_id=plan.id,
            billing_cycle=request.billing_cycle,
            status="pending",
            paypal_subscription_id=result["subscription_id"],
        )
        db.add(row)
    await db.commit()

    return CheckoutResponse(
        approval_url=result["approval_url"],
        paypal_subscription_id=result["subscription_id"],
    )


@router.post("/activate")
async def activate_subscription(
    request: ActivateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """
    Finalize a subscription after PayPal approval.

    PayPal redirects the buyer to /parent/settings/subscription/activate with
    ?subscription_id=I-XXXX. The activate page POSTs here. We look up the
    FamilySubscription that /checkout persisted — either a fresh pending row
    (paypal_subscription_id) or a STAGED plan change on a live subscription
    (pending_paypal_subscription_id) — confirm payment with PayPal, then
    apply the ACTIVATED transition / promote the staged checkout. On a plan
    change, the superseded PayPal subscription is cancelled at PayPal so the
    customer is never double-billed.
    """
    from datetime import timedelta

    from app.services.subscription_state import (
        apply_activated,
        promote_pending_checkout,
    )

    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == current_user.family_id,
                (
                    FamilySubscription.paypal_subscription_id
                    == request.paypal_subscription_id
                )
                | (
                    FamilySubscription.pending_paypal_subscription_id
                    == request.paypal_subscription_id
                ),
            )
        )
    )
    row = (await db.execute(query)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending subscription found for this PayPal subscription_id",
        )

    is_staged_change = (
        row.pending_paypal_subscription_id == request.paypal_subscription_id
    )

    if not is_staged_change and row.status == "active":
        # Idempotent re-entry — already activated (likely by webhook race)
        return {
            "status": "already_active",
            "subscription_id": str(row.id),
            "plan_name": row.plan.name if row.plan else None,
        }

    try:
        paypal_service = PayPalService()
        await asyncio.to_thread(
            paypal_service.execute_subscription,
            billing_agreement_id=request.paypal_subscription_id,
            token=request.paypal_subscription_id,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to execute PayPal agreement: {str(e)}",
        )

    billing_cycle = (
        row.pending_billing_cycle if is_staged_change else row.billing_cycle
    ) or "monthly"
    period_end = datetime.now(timezone.utc) + (
        timedelta(days=365) if billing_cycle == "annual" else timedelta(days=30)
    )

    if is_staged_change:
        sub, old_paypal_id = await promote_pending_checkout(
            db,
            paypal_subscription_id=request.paypal_subscription_id,
            period_end=period_end,
        )
        if sub is not None and old_paypal_id:
            # Stop billing on the superseded subscription. Best-effort: the
            # daily reconciliation sweep will surface any leftover.
            import logging
            try:
                await asyncio.to_thread(
                    PayPalService.cancel_subscription,
                    old_paypal_id,
                    reason="Superseded by plan change",
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed to cancel superseded PayPal sub %s",
                    old_paypal_id, exc_info=True,
                )
    else:
        sub = await apply_activated(
            db,
            paypal_subscription_id=request.paypal_subscription_id,
            period_end=period_end,
        )

    plan_name = None
    if sub is not None:
        plan_row = (
            await db.execute(
                select(SubscriptionPlan.name).where(
                    SubscriptionPlan.id == sub.plan_id
                )
            )
        ).scalar_one_or_none()
        plan_name = plan_row

    return {
        "status": "activated",
        "subscription_id": str(sub.id) if sub else None,
        "paypal_subscription_id": request.paypal_subscription_id,
        "plan_name": plan_name,
    }


@router.post("/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_parent_role),
):
    """
    Cancel the family's active subscription at end of current period.

    PayPal billing is cancelled immediately at their end (no future charges),
    but the family keeps the plan benefits until current_period_end via the
    cancel_at_period_end flag. The daily sweep job downgrades to Free after
    period_end passes.
    """
    import logging

    from app.services.subscription_state import apply_cancelled

    query = select(FamilySubscription).where(
        and_(
            FamilySubscription.family_id == current_user.family_id,
            FamilySubscription.status.in_(["active", "past_due", "payment_failed"]),
        )
    )
    subscription = (await db.execute(query)).scalar_one_or_none()
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active subscription found",
        )

    if subscription.paypal_subscription_id:
        try:
            await asyncio.to_thread(
                PayPalService.cancel_subscription,
                subscription.paypal_subscription_id,
                reason="User requested via app",
            )
        except Exception as e:
            # PayPal call failed but we still flag cancel locally;
            # log + continue. Webhook will reconcile if PayPal eventually fires.
            logging.warning(
                "PayPal cancel failed for %s: %s",
                subscription.paypal_subscription_id,
                e,
            )

    await apply_cancelled(
        db, paypal_subscription_id=subscription.paypal_subscription_id
    )
    await db.refresh(subscription)

    return {
        "status": "cancel_pending",
        "cancel_at_period_end": True,
        "period_end": str(subscription.current_period_end),
    }
