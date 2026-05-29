"""Detect a likely duplicate receipt scan within a short time window.

Public surface:
    DuplicateGuardService.check(db, family_id, payee_id, amount_cents)
        -> DupWarning | None

Logic:
- Skip immediately when payee_id is None (can't deduplicate without a payee).
- Look for an existing BudgetTransaction in the same family, with the same
  payee, created within the last 60 seconds, whose amount is within 1% of
  the incoming amount.
- Returns the MOST RECENT match (order by created_at desc, limit 1), or None.
- Amount tolerance: max(1, int(abs(amount_cents) * 0.01)) cents — at least
  1 cent so that tiny amounts still dedup correctly.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction
from app.schemas.budget import DupWarning


class DuplicateGuardService:

    WINDOW_SECONDS = 60
    AMOUNT_TOLERANCE = 0.01  # 1%

    @classmethod
    async def check(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee_id: Optional[UUID],
        amount_cents: int,
    ) -> Optional[DupWarning]:
        """Return a DupWarning if a likely duplicate exists, else None."""
        if payee_id is None:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=cls.WINDOW_SECONDS)
        tol = max(1, int(abs(amount_cents) * cls.AMOUNT_TOLERANCE))

        stmt = (
            select(BudgetTransaction)
            .where(and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.payee_id == payee_id,
                # Exclude soft-deleted rows so the recycle bin can't
                # resurrect a dup-warning on a re-scan.
                BudgetTransaction.deleted_at.is_(None),
                BudgetTransaction.created_at >= cutoff,
                BudgetTransaction.amount.between(
                    amount_cents - tol, amount_cents + tol
                ),
            ))
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None

        return DupWarning(
            existing_transaction_id=row.id,
            scanned_at=row.created_at,
            amount_cents=int(row.amount),
        )
