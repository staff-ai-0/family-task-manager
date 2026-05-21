"""
Daily subscription sweep — downgrade families whose
cancel_at_period_end=True and current_period_end < now() to status='cancelled'.

Scheduled by APScheduler on app startup, fires daily at 03:00 UTC.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import FamilySubscription


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


async def run_sweep():
    """Top-level entrypoint for the scheduled job. Creates its own session."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        n = await downgrade_expired_subscriptions(db)
        if n:
            logger.info("Sweep downgraded %d expired subscriptions", n)
