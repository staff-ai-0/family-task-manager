"""
Usage tracking service for premium feature metering.

Tracks per-family, per-feature usage counts by billing period (month).
"""
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
        cls, db: AsyncSession, family_id: UUID, feature: str, amount: int = 1
    ) -> int:
        """
        Increment the usage counter for a feature in the current month.

        Creates the record if it doesn't exist yet. Returns the new count.
        Use amount > 1 when a single API call produces multiple chargeable
        units (e.g. split transactions create N child legs at once).
        """
        if amount < 1:
            raise ValueError("amount must be >= 1")

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
                count=amount,
            )
            db.add(record)
        else:
            record.count += amount

        await db.commit()
        await db.refresh(record)
        return record.count

    @classmethod
    async def try_increment_within_limit(
        cls,
        db: AsyncSession,
        family_id: UUID,
        feature: str,
        limit: int,
        amount: int = 1,
    ) -> Optional[int]:
        """Atomically increment usage by *amount* only if it would not breach
        *limit*. Returns the new count on success, or None when the increment
        would exceed the limit.

        Single statement: INSERT ... ON CONFLICT DO UPDATE WHERE ... RETURNING.
        The (family_id, feature, period_start) unique constraint serializes
        concurrent callers at the row level, eliminating the read-then-write
        race in the require_feature → increment pattern (where two requests
        could each observe usage below the limit and both increment past it).

        Limit semantics:
          limit == -1  → unlimited (always increments)
          limit ==  0  → disabled  (always returns None)
          limit >  0   → numeric cap, increment iff current + amount <= limit
        """
        if amount < 1:
            raise ValueError("amount must be >= 1")
        if limit == 0:
            return None
        if limit != -1 and amount > limit:
            return None

        period = cls._current_period()
        stmt = pg_insert(UsageTracking).values(
            family_id=family_id,
            feature=feature,
            period_start=period,
            count=amount,
        )

        if limit == -1:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_usage_family_feature_period",
                set_={"count": UsageTracking.count + amount},
            )
        else:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_usage_family_feature_period",
                set_={"count": UsageTracking.count + amount},
                where=(UsageTracking.count + amount <= limit),
            )

        stmt = stmt.returning(UsageTracking.count)
        result = await db.execute(stmt)
        new_count = result.scalar()

        if new_count is None:
            # ON CONFLICT WHERE failed → over limit. The INSERT side cannot
            # produce a NULL because amount > 0, so reaching here means an
            # existing row was found and the predicate rejected the update.
            await db.rollback()
            return None

        await db.commit()
        return new_count

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
