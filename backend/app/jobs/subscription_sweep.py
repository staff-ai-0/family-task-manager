"""
Daily subscription sweep. Three passes:

1. downgrade_expired_subscriptions — cancel_at_period_end=True rows whose
   current_period_end passed → status='cancelled'.
2. downgrade_grace_expired_subscriptions — payment_failed rows whose dunning
   grace window (payment_failure_at + BILLING_GRACE_DAYS) fully elapsed →
   status='grace_expired' (explicit final status; resolves to the free plan).
3. reconcile_with_paypal — for every locally-live subscription, fetch the
   authoritative state from PayPal and converge local status +
   current_period_end. Catches anything a missed webhook (24h retry window
   expired during an outage) would otherwise leave drifted forever.

Scheduled by APScheduler on app startup, fires daily at 03:00 UTC.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.subscription import FamilySubscription
from app.services.subscription_state import (
    GRACE_EXPIRED_STATUS,
    notify_subscription_ended,
)


logger = logging.getLogger(__name__)


async def downgrade_expired_subscriptions(db: AsyncSession) -> int:
    """
    Find expired-cancellation subs and flip status to cancelled.

    Returns count of rows updated.
    """
    now = datetime.now(timezone.utc)
    query = select(FamilySubscription).where(
        and_(
            FamilySubscription.cancel_at_period_end == True,  # noqa: E712
            FamilySubscription.current_period_end < now,
            FamilySubscription.status != "cancelled",
        )
    )
    subs = (await db.execute(query)).scalars().all()
    for sub in subs:
        sub.status = "cancelled"
    if subs:
        await db.commit()
    return len(subs)


async def downgrade_grace_expired_subscriptions(db: AsyncSession) -> int:
    """
    Downgrade payment_failed subs whose dunning grace window has elapsed.

    The grace window is payment_failure_at + settings.BILLING_GRACE_DAYS
    (premium.get_family_plan keeps the family entitled inside it). After
    expiry we stamp the explicit final status 'grace_expired' so the family
    resolves to the free plan and the row records WHY it was downgraded.
    A later successful PayPal retry (PAYMENT.SALE.COMPLETED) still restores
    it via subscription_state.apply_payment_completed.

    Returns count of rows updated.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.BILLING_GRACE_DAYS
    )
    query = select(FamilySubscription).where(
        and_(
            FamilySubscription.status == "payment_failed",
            FamilySubscription.payment_failure_at != None,  # noqa: E711
            FamilySubscription.payment_failure_at < cutoff,
        )
    )
    subs = (await db.execute(query)).scalars().all()
    for sub in subs:
        sub.status = GRACE_EXPIRED_STATUS
        logger.info(
            "Grace expired for family %s (failure at %s) — downgraded to free",
            sub.family_id, sub.payment_failure_at,
        )
    if subs:
        await db.commit()
    # Final "subscription ended" notice — dispatched only for rows that went
    # through the payment_failed → grace_expired transition in THIS run (the
    # WHERE clause above filters status='payment_failed'), so repeated sweep
    # runs can never re-send it. Fire-and-forget, after the commit: an email
    # failure never blocks or rolls back the downgrade.
    for sub in subs:
        await notify_subscription_ended(db, sub)
    return len(subs)


# Local statuses worth reconciling against PayPal — every status that a
# missed webhook could leave stranded while PayPal still bills (or should be
# billing). 'pending' catches a buyer who approved the checkout but whose
# ACTIVATED webhook was missed and who never returned to /activate;
# 'grace_expired' catches a recovery (successful retry charge) whose
# PAYMENT.SALE.COMPLETED webhook was missed after the local downgrade.
# Only 'cancelled' and 'expired' stay excluded: they are terminal by our own
# action / PayPal's, and re-activating them here would fight the sweep's own
# downgrade passes. Rows without a paypal_subscription_id (free families)
# are excluded by the query below.
_RECONCILE_ALWAYS_STATUSES = ("active", "past_due", "payment_failed")

# 'pending' and 'grace_expired' are reconciled only while RECENT (age from
# updated_at — the last real state change: checkout refresh bumps it for
# pending, the grace-expiry downgrade bumps it for grace_expired). Without
# an age cap, every abandoned checkout (APPROVAL_PENDING forever) and every
# grace_expired row whose PayPal side sits SUSPENDED would be polled against
# the PayPal API nightly, forever — the candidate set only grows over time.
# The windows comfortably cover the real stranding scenarios: a missed
# ACTIVATED webhook is caught the very next night, and PayPal's own dunning
# retry schedule gives up well inside 60 days.
_RECONCILE_MAX_AGE = {
    "pending": timedelta(days=7),
    GRACE_EXPIRED_STATUS: timedelta(days=60),
}


def _parse_paypal_time(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def reconcile_with_paypal(db: AsyncSession) -> int:
    """
    Converge each locally-live subscription with PayPal's view of it.

    Per-sub try/except: one PayPal API failure (or one weird row) must not
    kill the pass for everyone else. Returns the number of rows changed.
    """
    from app.services.paypal_service import PayPalService

    now = datetime.now(timezone.utc)
    query = select(FamilySubscription).where(
        and_(
            or_(
                FamilySubscription.status.in_(list(_RECONCILE_ALWAYS_STATUSES)),
                *[
                    and_(
                        FamilySubscription.status == status_,
                        FamilySubscription.updated_at >= now - max_age,
                    )
                    for status_, max_age in _RECONCILE_MAX_AGE.items()
                ],
            ),
            FamilySubscription.paypal_subscription_id != None,  # noqa: E711
        )
    )
    subs = (await db.execute(query)).scalars().all()

    changed = 0
    for sub in subs:
        # Captured before any commit/rollback: a rollback expires ORM
        # attributes and re-loading them lazily in the except branch would
        # raise (async session, no greenlet context).
        paypal_id = sub.paypal_subscription_id
        try:
            remote = await asyncio.to_thread(
                PayPalService.get_subscription, paypal_id
            )
            remote_status = (remote.get("status") or "").upper()
            next_billing = _parse_paypal_time(remote.get("next_billing_at"))
            dirty = False

            if remote_status == "ACTIVE":
                if sub.status != "active":
                    # PayPal keeps a subscription ACTIVE while it retries a
                    # failed payment itself (SUSPENDED only comes after its
                    # retries are exhausted), so ACTIVE alone is NOT proof of
                    # recovery for a row in dunning. Only treat it as
                    # recovered when PayPal reports a next_billing_time
                    # NEWER than our failure timestamp — a successful charge
                    # advances it a full cycle past the failure, whereas
                    # mid-retry it still points at the outstanding (failed)
                    # billing date. Otherwise leave the grace clock running:
                    # the PAYMENT.SALE.COMPLETED webhook or a later sweep
                    # converges it once the retry actually succeeds.
                    failure_at = sub.payment_failure_at
                    if failure_at is not None and failure_at.tzinfo is None:
                        failure_at = failure_at.replace(tzinfo=timezone.utc)
                    mid_retry = (
                        sub.status in ("payment_failed", GRACE_EXPIRED_STATUS)
                        and failure_at is not None
                        and (next_billing is None or next_billing <= failure_at)
                    )
                    if mid_retry:
                        logger.info(
                            "Reconcile: sub %s local=%s, PayPal=ACTIVE but no "
                            "payment newer than failure at %s — leaving grace "
                            "running",
                            paypal_id, sub.status, failure_at,
                        )
                    else:
                        logger.warning(
                            "Reconcile: sub %s local=%s but PayPal=ACTIVE — restoring",
                            paypal_id, sub.status,
                        )
                        sub.status = "active"
                        sub.payment_failure_at = None
                        sub.current_period_start = (
                            sub.current_period_start or now
                        )
                        dirty = True
                if sub.status == "active" and next_billing is not None:
                    local_end = sub.current_period_end
                    if local_end is not None and local_end.tzinfo is None:
                        local_end = local_end.replace(tzinfo=timezone.utc)
                    if local_end is None or abs(
                        (next_billing - local_end).total_seconds()
                    ) > 60:
                        logger.info(
                            "Reconcile: sub %s period_end %s -> %s (PayPal)",
                            paypal_id,
                            sub.current_period_end, next_billing,
                        )
                        sub.current_period_end = next_billing
                        dirty = True
            elif remote_status == "SUSPENDED":
                # grace_expired stays grace_expired: the family is already
                # downgraded and PayPal is not billing. Re-stamping
                # payment_failed here would restart entitlement/dunning and
                # flip-flop with the grace-expiry pass every night.
                if sub.status not in ("payment_failed", GRACE_EXPIRED_STATUS):
                    logger.warning(
                        "Reconcile: sub %s local=%s but PayPal=SUSPENDED — dunning",
                        paypal_id, sub.status,
                    )
                    sub.status = "payment_failed"
                    sub.payment_failure_at = sub.payment_failure_at or now
                    dirty = True
            elif remote_status == "CANCELLED":
                if not sub.cancel_at_period_end:
                    logger.warning(
                        "Reconcile: sub %s local=%s but PayPal=CANCELLED — flagging",
                        paypal_id, sub.status,
                    )
                    sub.cancel_at_period_end = True
                    sub.cancelled_at = sub.cancelled_at or now
                    dirty = True
                # Benefits still run until current_period_end; pass 1 of the
                # sweep downgrades once it passes. But if the period is
                # already over, close it out now.
                period_end = sub.current_period_end
                if period_end is not None and period_end.tzinfo is None:
                    period_end = period_end.replace(tzinfo=timezone.utc)
                if (
                    period_end is None or period_end < now
                ) and sub.status != "cancelled":
                    sub.status = "cancelled"
                    dirty = True
            elif remote_status == "EXPIRED":
                if sub.status != "expired":
                    logger.warning(
                        "Reconcile: sub %s local=%s but PayPal=EXPIRED — downgrading",
                        paypal_id, sub.status,
                    )
                    sub.status = "expired"
                    dirty = True
            else:
                # APPROVAL_PENDING / APPROVED / unknown — nothing to converge.
                logger.info(
                    "Reconcile: sub %s PayPal status %s — no action",
                    paypal_id, remote_status,
                )

            if dirty:
                await db.commit()
                changed += 1
        except Exception:
            # One failure must not kill the whole pass.
            await db.rollback()
            logger.exception(
                "Reconcile failed for sub %s", paypal_id
            )
    return changed


async def run_sweep():
    """Top-level entrypoint for the scheduled job. Creates its own session."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            n = await downgrade_expired_subscriptions(db)
            if n:
                logger.info("Sweep downgraded %d expired subscriptions", n)
    except Exception:
        logger.exception("Subscription sweep (cancel-expiry pass) failed")

    try:
        async with AsyncSessionLocal() as db:
            n = await downgrade_grace_expired_subscriptions(db)
            if n:
                logger.info("Sweep downgraded %d grace-expired subscriptions", n)
    except Exception:
        logger.exception("Subscription sweep (grace-expiry pass) failed")

    if not settings.PAYPAL_CLIENT_ID:
        logger.info("PayPal not configured — skipping reconciliation pass")
        return
    try:
        async with AsyncSessionLocal() as db:
            n = await reconcile_with_paypal(db)
            if n:
                logger.info("Sweep reconciled %d subscriptions with PayPal", n)
    except Exception:
        logger.exception("Subscription sweep (PayPal reconciliation) failed")
