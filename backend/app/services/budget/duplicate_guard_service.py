"""Detect a likely duplicate receipt scan.

Public surface:
    DuplicateGuardService.check(db, family_id, payee_id, amount_cents, transaction_date)
        -> DupMatch | None

Logic (in priority order):
1. Date-based (preferred): same date + same payee + amount within 1%.
   This catches scanned receipts re-imported from bank statements regardless
   of when the original was created.
2. Window fallback: if no transaction_date provided, look back WINDOW_DAYS for
   same payee + amount within 1% (e.g. bulk scan loop with unknown dates).

Returns the MOST RECENT match (order by created_at desc, limit 1), or None.
Amount tolerance: max(1, int(abs(amount_cents) * 0.01)) — at least 1 cent.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction
from app.schemas.budget import DupWarning


class DuplicateGuardService:

    WINDOW_DAYS = 7
    AMOUNT_TOLERANCE = 0.01  # 1%

    @classmethod
    async def check(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee_id: Optional[UUID],
        amount_cents: int,
        transaction_date: Optional[date] = None,
    ) -> Optional["DupMatch"]:
        """Return a DupMatch if a likely duplicate exists, else None."""
        if payee_id is None:
            return None

        tol = max(1, int(abs(amount_cents) * cls.AMOUNT_TOLERANCE))
        amount_range = BudgetTransaction.amount.between(
            amount_cents - tol, amount_cents + tol
        )
        base_filter = and_(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.payee_id == payee_id,
            BudgetTransaction.deleted_at.is_(None),
            amount_range,
        )

        if transaction_date is not None:
            # Primary path: exact date match — catches bank-import vs re-scan.
            date_filter = BudgetTransaction.date == transaction_date
        else:
            # Fallback: created_at window (bulk scan without confirmed dates).
            cutoff = datetime.now(timezone.utc) - timedelta(days=cls.WINDOW_DAYS)
            date_filter = BudgetTransaction.created_at >= cutoff

        stmt = (
            select(BudgetTransaction)
            .where(and_(base_filter, date_filter))
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None

        return DupMatch(
            existing_transaction=row,
            warning=DupWarning(
                existing_transaction_id=row.id,
                scanned_at=row.created_at,
                amount_cents=int(row.amount),
            ),
        )


class DupMatch:
    """Wraps the full ORM row so callers can inspect richness."""

    def __init__(self, existing_transaction: BudgetTransaction, warning: DupWarning):
        self.existing_transaction = existing_transaction
        self.warning = warning

    @property
    def existing_has_image(self) -> bool:
        return bool(self.existing_transaction.receipt_image_path)

    @property
    def existing_transaction_id(self) -> UUID:
        return self.existing_transaction.id
