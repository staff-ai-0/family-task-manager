"""
Subscription state-transition service.

Pure functions that mutate a FamilySubscription row in response to PayPal
lifecycle events. Called by both the /activate route (synchronous return
from PayPal redirect) and the /webhook handler (asynchronous PayPal IPN),
plus the daily sweep/reconciliation job.

All functions are idempotent: re-applying the same event has no effect.

Billing lifecycle emails (dunning / activated / cancelled) are dispatched
from the genuine transitions here — never from the idempotent re-entry
paths — and are strictly fire-and-forget: an email failure can never block
or roll back a state change.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.subscription import FamilySubscription, SubscriptionPlan

logger = logging.getLogger(__name__)

# Explicit final status the sweep stamps on a payment_failed sub once the
# dunning grace window has fully elapsed. NOT in premium.ENTITLED_STATUSES,
# so the family resolves to the free plan.
GRACE_EXPIRED_STATUS = "grace_expired"

# How close to current_period_end a PAYMENT.SALE.COMPLETED on an ACTIVE sub
# must land to count as a genuine renewal. The INITIAL activation charge
# fires within minutes of activation — while the freshly-set period end is
# still ~a full cycle away — so advancing on it would double-extend the
# entitlement window (activation already set current_period_end). Genuine
# renewals bill at (or within a couple of days of) the period boundary.
RENEWAL_WINDOW = timedelta(days=3)


def _cycle_delta(billing_cycle: Optional[str]) -> timedelta:
    """Length of one billing cycle."""
    return timedelta(days=365) if billing_cycle == "annual" else timedelta(days=30)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _find(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    result = await db.execute(
        select(FamilySubscription).where(
            FamilySubscription.paypal_subscription_id == paypal_subscription_id
        )
    )
    return result.scalar_one_or_none()


async def _plan_display_name(db: AsyncSession, sub: FamilySubscription) -> str:
    """Plan display name for email copy (explicit query — no lazy load in async)."""
    try:
        name = (
            await db.execute(
                select(SubscriptionPlan.display_name).where(
                    SubscriptionPlan.id == sub.plan_id
                )
            )
        ).scalar_one_or_none()
        return name or "Premium"
    except Exception:
        return "Premium"


async def _notify_activated(db: AsyncSession, sub: FamilySubscription) -> None:
    try:
        from app.services.email_service import EmailService

        plan_name = await _plan_display_name(db, sub)
        await EmailService.send_subscription_activated_email(
            db, sub.family_id, plan_name=plan_name
        )
    except Exception:
        logger.warning(
            "subscription-activated email dispatch failed (family %s)",
            sub.family_id, exc_info=True,
        )


async def _notify_cancelled(db: AsyncSession, sub: FamilySubscription) -> None:
    try:
        from app.services.email_service import EmailService

        plan_name = await _plan_display_name(db, sub)
        await EmailService.send_subscription_cancelled_email(
            db, sub.family_id,
            plan_name=plan_name,
            period_end=_aware(sub.current_period_end),
        )
    except Exception:
        logger.warning(
            "subscription-cancelled email dispatch failed (family %s)",
            sub.family_id, exc_info=True,
        )


async def _notify_payment_failed(db: AsyncSession, sub: FamilySubscription) -> None:
    try:
        from app.services.email_service import EmailService

        plan_name = await _plan_display_name(db, sub)
        failure_at = _aware(sub.payment_failure_at) or datetime.now(timezone.utc)
        await EmailService.send_payment_failed_email(
            db, sub.family_id,
            plan_name=plan_name,
            grace_deadline=failure_at + timedelta(days=settings.BILLING_GRACE_DAYS),
        )
    except Exception:
        logger.warning(
            "payment-failed email dispatch failed (family %s)",
            sub.family_id, exc_info=True,
        )


async def notify_subscription_ended(
    db: AsyncSession, sub: FamilySubscription
) -> None:
    """Final 'subscription ended' notice — dunning grace elapsed, family
    downgraded to the free plan.

    Called by the sweep at the exact moment it stamps GRACE_EXPIRED_STATUS.
    The sweep's WHERE clause (status='payment_failed') guarantees a row
    passes through that transition exactly once, so repeated sweep runs can
    never re-send this email (same one-shot-transition guard as dunning).
    Fire-and-forget: an email failure never blocks the downgrade.
    """
    try:
        from app.services.email_service import EmailService

        plan_name = await _plan_display_name(db, sub)
        await EmailService.send_subscription_ended_email(
            db, sub.family_id, plan_name=plan_name
        )
    except Exception:
        logger.warning(
            "subscription-ended email dispatch failed (family %s)",
            sub.family_id, exc_info=True,
        )


async def apply_activated(
    db: AsyncSession,
    paypal_subscription_id: str,
    period_end: datetime,
    trial_end_at: Optional[datetime] = None,
) -> Optional[FamilySubscription]:
    """Mark sub active. Idempotent.

    Also handles a PayPal-side re-activation of a suspended/payment_failed
    sub (BILLING.SUBSCRIPTION.ACTIVATED fires again) by clearing the
    dunning marker.
    """
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
    sub.payment_failure_at = None
    if trial_end_at is not None:
        sub.trial_end_at = trial_end_at
    await db.commit()
    await db.refresh(sub)
    await _notify_activated(db, sub)
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
    await _notify_cancelled(db, sub)
    return sub


async def apply_payment_failed(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    """Recurring payment failed (or PayPal suspended the sub) — start the
    dunning grace period (settings.BILLING_GRACE_DAYS).

    The family keeps entitlements while within the grace window
    (premium.get_family_plan honors payment_failed + payment_failure_at);
    the daily sweep downgrades to GRACE_EXPIRED_STATUS afterwards.
    """
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None
    if sub.status == "payment_failed":
        return sub  # idempotent — keep original payment_failure_at

    sub.status = "payment_failed"
    sub.payment_failure_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sub)
    await _notify_payment_failed(db, sub)
    return sub


async def apply_payment_completed(
    db: AsyncSession,
    paypal_subscription_id: str,
    period_end: Optional[datetime] = None,
) -> Optional[FamilySubscription]:
    """A recurring payment succeeded (PAYMENT.SALE.COMPLETED).

    - If the sub is in dunning (payment_failed) or already grace-expired,
      this is the recovery signal: flip back to active, clear the failure
      marker, and advance the period.
    - If the sub is active, this is a renewal: advance current_period_end
      by one billing cycle (it would otherwise stay frozen at
      activation+30d forever). The INITIAL activation charge also arrives
      as PAYMENT.SALE.COMPLETED, but activation already set
      current_period_end — so the advance only happens when the sale lands
      near/after the current period end (see RENEWAL_WINDOW); otherwise the
      event is treated as the already-accounted activation charge (or a
      replay) and ignored.

    *period_end* overrides the computed next period end when the caller has
    an authoritative value (e.g. billing_info.next_billing_time) — an
    authoritative value bypasses the renewal-proximity guard (it is safe to
    converge on PayPal's own next_billing_time at any point in the cycle).
    """
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None

    now = datetime.now(timezone.utc)
    computed_period_end = period_end is None
    if period_end is None:
        # Anchor at the current period end when it is still in the future
        # (early retry), else at now (renewal / late recovery).
        base = _aware(sub.current_period_end)
        if base is None or base < now:
            base = now
        period_end = base + _cycle_delta(sub.billing_cycle)

    if sub.status in ("payment_failed", GRACE_EXPIRED_STATUS, "suspended"):
        sub.status = "active"
        sub.payment_failure_at = None
        sub.current_period_end = period_end
        await db.commit()
        await db.refresh(sub)
        logger.info(
            "Subscription %s recovered via successful payment", paypal_subscription_id
        )
        await _notify_activated(db, sub)
        return sub

    if sub.status == "active":
        current = _aware(sub.current_period_end)
        if computed_period_end and current is not None and (
            now < current - RENEWAL_WINDOW
        ):
            # The paid-through date is still comfortably in the future:
            # this sale is the INITIAL activation charge (activation just
            # set current_period_end) or a replayed event. Advancing again
            # would double-extend the entitlement window. Idempotent no-op.
            logger.info(
                "PAYMENT.SALE.COMPLETED for active sub %s well before period "
                "end %s — treating as initial/duplicate charge, not advancing",
                paypal_subscription_id, current,
            )
            return sub
        # Renewal — only ever move the period end forward (a replayed or
        # out-of-order sale event must not shrink the entitlement window).
        if current is None or period_end > current:
            sub.current_period_end = period_end
            await db.commit()
            await db.refresh(sub)
        return sub

    # pending/cancelled/expired: a stray sale event — leave state alone.
    logger.info(
        "PAYMENT.SALE.COMPLETED for sub %s in status %s — no transition",
        paypal_subscription_id, sub.status,
    )
    return sub


async def apply_expired(
    db: AsyncSession, paypal_subscription_id: str
) -> Optional[FamilySubscription]:
    """BILLING.SUBSCRIPTION.EXPIRED — the sub ran its full course at PayPal.

    Not entitled anymore: status='expired' resolves the family to free.
    """
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None
    if sub.status == "expired":
        return sub  # idempotent

    sub.status = "expired"
    await db.commit()
    await db.refresh(sub)
    return sub


async def mark_for_review(
    db: AsyncSession, paypal_subscription_id: str, reason: str
) -> Optional[FamilySubscription]:
    """Flag a subscription for operator review (refunds/reversals).

    Deliberately conservative: a refund or reversal event does NOT
    automatically downgrade the family — a partial/goodwill refund would
    otherwise kick a paying customer to free. The operator resolves the
    flag manually (and PayPal suspends/cancels the sub itself when the
    money situation warrants it, which we do handle automatically).
    """
    sub = await _find(db, paypal_subscription_id)
    if sub is None:
        return None

    sub.needs_review = True
    sub.review_reason = reason[:255]
    await db.commit()
    await db.refresh(sub)
    logger.warning(
        "Subscription %s (family %s) flagged for review: %s",
        paypal_subscription_id, sub.family_id, reason,
    )
    return sub


async def promote_pending_checkout(
    db: AsyncSession,
    paypal_subscription_id: str,
    period_end: Optional[datetime] = None,
) -> Tuple[Optional[FamilySubscription], Optional[str]]:
    """Promote a staged (pending_*) checkout to the live subscription.

    Used when a family that already had a live subscription completed a
    plan-change checkout: /checkout staged the new plan + PayPal sub id in
    the pending_* columns; on payment confirmation this swaps them in and
    returns the superseded PayPal subscription id so the caller can cancel
    it at PayPal (route layer — this module stays PayPal-API-free).

    Returns (sub, old_paypal_subscription_id). (None, None) when no row has
    this id staged.
    """
    result = await db.execute(
        select(FamilySubscription).where(
            FamilySubscription.pending_paypal_subscription_id
            == paypal_subscription_id
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return None, None

    old_paypal_id = sub.paypal_subscription_id
    now = datetime.now(timezone.utc)

    sub.plan_id = sub.pending_plan_id or sub.plan_id
    sub.billing_cycle = sub.pending_billing_cycle or sub.billing_cycle
    sub.paypal_subscription_id = paypal_subscription_id
    sub.pending_plan_id = None
    sub.pending_billing_cycle = None
    sub.pending_paypal_subscription_id = None
    sub.status = "active"
    sub.current_period_start = now
    sub.current_period_end = period_end or (now + _cycle_delta(sub.billing_cycle))
    sub.payment_failure_at = None
    sub.cancel_at_period_end = False
    sub.cancelled_at = None
    await db.commit()
    await db.refresh(sub)
    await _notify_activated(db, sub)
    return sub, (old_paypal_id if old_paypal_id != paypal_subscription_id else None)
