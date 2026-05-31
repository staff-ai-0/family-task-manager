"""Find and merge duplicate transactions within a family.

A "duplicate" is two rows with:
  - same family_id
  - same payee_id (non-null)
  - same date
  - amount within 1% tolerance
  - neither is soft-deleted
  - neither is a split child (parent_id IS NULL)

When merging a pair, a "richness score" picks the winner. The loser is
soft-deleted; its receipt image path (if any) is transferred to the winner
first so no GCS object is orphaned.

Richness score (higher = keep):
  +20  has receipt_image_path
  +10  has notes (non-empty)
   +5  has category_id
   +2  per transaction item (via BudgetTransactionItem relationship)
   +1  is cleared
   -5  was created by CSV import (imported_id is set, no receipt image)
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransaction, BudgetTransactionItem

logger = logging.getLogger(__name__)


def _score(txn: BudgetTransaction, item_count: int) -> int:
    s = 0
    if txn.receipt_image_path:
        s += 20
    if txn.notes and txn.notes.strip():
        s += 10
    if txn.category_id:
        s += 5
    s += item_count * 2
    if txn.cleared:
        s += 1
    if txn.imported_id and not txn.receipt_image_path:
        s -= 5
    return s


class DeduplicateService:

    AMOUNT_TOLERANCE = 0.01

    @classmethod
    async def run(
        cls,
        db: AsyncSession,
        family_id: UUID,
        deleted_by_id: Optional[UUID] = None,
        dry_run: bool = False,
    ) -> dict:
        """Find and merge all duplicate pairs for the family.

        Returns:
            {merged: int, skipped: int, pairs: list[dict]}
        """
        # Fetch all non-deleted, non-split-child transactions that have a payee.
        stmt = (
            select(BudgetTransaction)
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
                BudgetTransaction.parent_id.is_(None),
                BudgetTransaction.payee_id.isnot(None),
            )
            .order_by(BudgetTransaction.date, BudgetTransaction.payee_id, BudgetTransaction.created_at)
        )
        rows = list((await db.execute(stmt)).scalars().all())

        # Count items per transaction in one query.
        item_count_stmt = (
            select(
                BudgetTransactionItem.transaction_id,
                func.count(BudgetTransactionItem.id).label("cnt"),
            )
            .where(BudgetTransactionItem.transaction_id.in_([r.id for r in rows]))
            .group_by(BudgetTransactionItem.transaction_id)
        )
        item_counts: dict[UUID, int] = {
            row.transaction_id: row.cnt
            for row in (await db.execute(item_count_stmt)).all()
        }

        # Group rows into duplicate clusters (same date + payee + amount±1%).
        seen_ids: set[UUID] = set()
        merged = 0
        skipped = 0
        pairs: list[dict] = []

        for i, a in enumerate(rows):
            if a.id in seen_ids:
                continue
            tol = max(1, int(abs(int(a.amount)) * cls.AMOUNT_TOLERANCE))
            for b in rows[i + 1:]:
                if b.id in seen_ids:
                    continue
                if b.date != a.date:
                    break  # rows are sorted by date; once past, no more matches
                if b.payee_id != a.payee_id:
                    continue
                if not (int(a.amount) - tol <= int(b.amount) <= int(a.amount) + tol):
                    continue
                # Found a dup pair (a, b).
                a_score = _score(a, item_counts.get(a.id, 0))
                b_score = _score(b, item_counts.get(b.id, 0))
                keeper, loser = (a, b) if a_score >= b_score else (b, a)

                pairs.append({
                    "keeper_id": str(keeper.id),
                    "loser_id": str(loser.id),
                    "keeper_score": max(a_score, b_score),
                    "loser_score": min(a_score, b_score),
                    "date": str(a.date),
                    "amount_cents": int(a.amount),
                })
                seen_ids.add(loser.id)

                if not dry_run:
                    await cls._merge(db, keeper, loser, deleted_by_id)
                    merged += 1
                else:
                    skipped += 1

        if not dry_run:
            await db.commit()

        return {"merged": merged, "skipped": skipped, "pairs": pairs, "dry_run": dry_run}

    @classmethod
    async def _merge(
        cls,
        db: AsyncSession,
        keeper: BudgetTransaction,
        loser: BudgetTransaction,
        deleted_by_id: Optional[UUID],
    ) -> None:
        # Transfer image from loser to keeper if keeper lacks one.
        if loser.receipt_image_path and not keeper.receipt_image_path:
            keeper.receipt_image_path = loser.receipt_image_path

        # Enrich keeper notes if loser has richer notes.
        if loser.notes and len(loser.notes) > len(keeper.notes or ""):
            keeper.notes = loser.notes

        # Inherit category if keeper has none.
        if loser.category_id and not keeper.category_id:
            keeper.category_id = loser.category_id

        # Soft-delete the loser.
        loser.deleted_at = datetime.now(timezone.utc)
        loser.deleted_by_id = deleted_by_id

        db.add(keeper)
        db.add(loser)
        logger.info("dedup: kept %s, removed %s (date=%s amt=%s)", keeper.id, loser.id, keeper.date, keeper.amount)
