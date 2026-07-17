"""Find and merge duplicate transactions within a family.

A "duplicate" is two rows satisfying BOTH of:
  1. Same family_id + account_id + date + amount within 1%
  2. At most one of the pair has a receipt image (if both have images
     they could be two separate purchases — skip to avoid data loss)
  3. Neither is soft-deleted or a split child (parent_id IS NULL)

Payee names are intentionally NOT compared: bank statements often use the
payment-terminal name ("KIOSKOS MIX") while receipt scans use the merchant
name ("Cinépolis Cumbres Monterrey"). Matching on account+date+amount is a
stronger and more reliable signal than payee name equality.

When merging a pair, a richness score picks the winner:
  +20  has receipt_image_path
  +10  has notes (non-empty)
   +5  has category_id
   +2  per transaction item
   +1  is cleared
   -5  was created by CSV import (imported_id set, no receipt image)

The loser is soft-deleted; its receipt image path (if any) is transferred to
the winner so no GCS object is orphaned.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
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
        stmt = (
            select(BudgetTransaction)
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
                BudgetTransaction.parent_id.is_(None),
            )
            .order_by(BudgetTransaction.date, BudgetTransaction.account_id, BudgetTransaction.created_at)
        )
        rows = list((await db.execute(stmt)).scalars().all())

        # Count items per transaction in one query.
        if rows:
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
        else:
            item_counts = {}

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
                # Rows sorted by date — once past this date, stop inner scan.
                if b.date != a.date:
                    break
                # Must be same account (same card/account means same purchase).
                if b.account_id != a.account_id:
                    continue
                # Amount within tolerance.
                if not (int(a.amount) - tol <= int(b.amount) <= int(a.amount) + tol):
                    continue
                # Safety: if BOTH have receipt images, skip — could be two
                # separate purchases for the same amount on the same day.
                if a.receipt_image_path and b.receipt_image_path:
                    logger.info(
                        "dedup: skipping pair %s/%s — both have receipt images",
                        a.id, b.id,
                    )
                    continue

                a_score = _score(a, item_counts.get(a.id, 0))
                b_score = _score(b, item_counts.get(b.id, 0))
                keeper, loser = (a, b) if a_score >= b_score else (b, a)

                pairs.append({
                    "keeper_id": str(keeper.id),
                    "keeper_payee": getattr(keeper, "_payee_name", None),
                    "loser_id": str(loser.id),
                    "loser_payee": getattr(loser, "_payee_name", None),
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

        if not dry_run and merged > 0:
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
        logger.info(
            "dedup: kept %s (score), removed %s | date=%s amt=%s",
            keeper.id, loser.id, keeper.date, keeper.amount,
        )
