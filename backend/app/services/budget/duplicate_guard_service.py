"""Detect a likely duplicate receipt scan.

Public surface:
    DuplicateGuardService.check(db, family_id, payee_id, amount_cents,
                                transaction_date, account_id)
        -> DupMatch | None

Logic (two-pass):
1. Date + payee + amount ±1%: exact payee match, same date.
2. Date + account + amount ±1%: account-based fallback for cases where the
   bank statement uses a different name than the receipt (e.g. "KIOSKOS MIX"
   vs "Cinépolis Cumbres Monterrey"). Only fires if account_id is provided.

Returns the MOST RECENT match, or None.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction
from app.schemas.budget import DupWarning


class DuplicateGuardService:

    WINDOW_DAYS = 7
    AMOUNT_TOLERANCE = 0.01

    @classmethod
    async def check(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee_id: Optional[UUID],
        amount_cents: int,
        transaction_date: Optional[date] = None,
        account_id: Optional[UUID] = None,
    ) -> Optional["DupMatch"]:
        """Return a DupMatch if a likely duplicate exists, else None."""
        tol = max(1, int(abs(amount_cents) * cls.AMOUNT_TOLERANCE))
        amount_range = BudgetTransaction.amount.between(amount_cents - tol, amount_cents + tol)
        base = and_(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_(None),
            amount_range,
        )

        if transaction_date is not None:
            date_filter = BudgetTransaction.date == transaction_date
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=cls.WINDOW_DAYS)
            date_filter = BudgetTransaction.created_at >= cutoff

        # Pass 1: payee match (most precise).
        if payee_id is not None:
            row = await cls._query(db, and_(base, date_filter, BudgetTransaction.payee_id == payee_id))
            if row:
                return DupMatch(row)

        # Pass 2: account match (catches bank-name vs receipt-name mismatch).
        if account_id is not None:
            row = await cls._query(db, and_(base, date_filter, BudgetTransaction.account_id == account_id))
            if row:
                return DupMatch(row)

        return None

    @classmethod
    async def _query(cls, db, where_clause) -> Optional[BudgetTransaction]:
        stmt = (
            select(BudgetTransaction)
            .where(where_clause)
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()


class DupMatch:
    """Wraps the full ORM row so callers can inspect richness."""

    def __init__(self, txn: BudgetTransaction):
        self.existing_transaction = txn

    @property
    def existing_has_image(self) -> bool:
        return bool(self.existing_transaction.receipt_image_path)

    @property
    def existing_transaction_id(self) -> UUID:
        return self.existing_transaction.id

    @property
    def warning(self) -> DupWarning:
        return DupWarning(
            existing_transaction_id=self.existing_transaction.id,
            scanned_at=self.existing_transaction.created_at,
            amount_cents=int(self.existing_transaction.amount),
        )
