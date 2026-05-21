"""
Subscription state-transition service.

Pure functions that mutate a FamilySubscription row in response to PayPal
lifecycle events. Called by both the /activate route (synchronous return
from PayPal redirect) and the /webhook handler (asynchronous PayPal IPN).

All functions are idempotent: re-applying the same event has no effect.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import FamilySubscription


async def _find(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    result = await db.execute(
        select(FamilySubscription).where(
            FamilySubscription.paypal_subscription_id == paypal_subscription_id
        )
    )
    return result.scalar_one_or_none()


async def apply_activated(
    db: AsyncSession,
    paypal_subscription_id: str,
    period_end: datetime,
    trial_end_at: Optional[datetime] = None,
) -> Optional[FamilySubscription]:
    """Mark sub active. Idempotent."""
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None
    if sub.status == "active":
        return sub  # idempotent

    sub.status = "active"
    sub.current_period_end = period_end
    sub.current_period_start = sub.current_period_start or datetime.now(
        timezone.utc
    )
    sub.trial_end_at = trial_end_at
    await db.commit()
    await db.refresh(sub)
    return sub


async def apply_cancelled(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    """User (or PayPal) cancelled — flag for downgrade at period_end."""
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None
    if sub.cancel_at_period_end:
        return sub  # idempotent

    sub.cancel_at_period_end = True
    sub.cancelled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    return sub


async def apply_payment_failed(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    """Recurring payment failed — start 3-day grace period."""
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None

    sub.status = "payment_failed"
    sub.payment_failure_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    return sub
