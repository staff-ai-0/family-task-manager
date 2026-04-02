"""
Usage tracking service for premium feature metering.

Tracks per-family, per-feature usage counts by billing period (month).
"""
from datetime import date
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import UsageTracking


class UsageService:
    """Manages feature usage counters for premium gating."""

    @classmethod
    def _current_period(cls) -> date:
        """Return the first day of the current month as the period key."""
        today = date.today()
        return today.replace(day=1)

    @classmethod
    async def get_usage(
        cls, db: AsyncSession, family_id: UUID, feature: str, period: date | None = None
    ) -> int:
        """
        Get the current usage count for a feature in a given period.

        Returns 0 if no record exists.
        """
        if period is None:
            period = cls._current_period()

        query = select(UsageTracking).where(
            and_(
                UsageTracking.family_id == family_id,
                UsageTracking.feature == feature,
                UsageTracking.period_start == period,
            )
        )
        result = await db.execute(query)
        record = result.scalar_one_or_none()
        return record.count if record else 0

    @classmethod
    async def increment(
        cls, db: AsyncSession, family_id: UUID, feature: str
    ) -> int:
        """
        Increment the usage counter for a feature in the current month.

        Creates the record if it doesn't exist yet. Returns the new count.
        """
        period = cls._current_period()

        query = select(UsageTracking).where(
            and_(
                UsageTracking.family_id == family_id,
                UsageTracking.feature == feature,
                UsageTracking.period_start == period,
            )
        )
        result = await db.execute(query)
        record = result.scalar_one_or_none()

        if record is None:
            record = UsageTracking(
                family_id=family_id,
                feature=feature,
                period_start=period,
                count=1,
            )
            db.add(record)
        else:
            record.count += 1

        await db.commit()
        await db.refresh(record)
        return record.count

    @classmethod
    async def check_limit(
        cls, db: AsyncSession, family_id: UUID, feature: str, limit: int
    ) -> bool:
        """
        Check whether the family is still within its usage limit.

        Special values:
          limit == -1  → unlimited (always True)
          limit ==  0  → disabled  (always False)
        Otherwise returns True when current usage < limit.
        """
        if limit == -1:
            return True
        if limit == 0:
            return False

        current = await cls.get_usage(db, family_id, feature)
        return current < limit
