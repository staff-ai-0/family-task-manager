"""Find and merge duplicate transactions within a family.

A "duplicate" is two or more rows satisfying ALL of:
  1. Same family_id + account_id + date + amount within 1%
  2. At most one of them has a receipt image (if several do, they could be
     separate purchases for the same amount — the whole group is refused)
  3. None is soft-deleted, a split child, or a split parent

Payee names are intentionally NOT compared: bank statements often use the
payment-terminal name ("KIOSKOS MIX") while receipt scans use the merchant
name ("Cinépolis Cumbres Monterrey"). Matching on account+date+amount is a
stronger and more reliable signal than payee name equality.

Duplicates are resolved per GROUP, not per pair. A pairwise sweep is unsafe
here: once a row loses a comparison it is soft-deleted, and a pairwise loop
would keep using that tombstone as a merge candidate — re-deleting it, merging
later rows *into* it, and leaving the real duplicates alive while reporting
them merged. Collecting the whole equivalence group first, picking one keeper,
and folding every other member into it makes that impossible by construction:
a group of N always leaves exactly one live row and N-1 soft-deleted ones.

Within a group a richness score picks the keeper:
  +20  has receipt_image_path
  +10  has notes (non-empty)
   +5  has category_id
   +2  per transaction item
   +1  is cleared
   -5  was created by CSV import (imported_id set, no receipt image)

Losers are soft-deleted; a loser's receipt image is MOVED (not copied) to the
keeper when the keeper has none, so no two live rows ever reference the same
stored object.
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
    def _within_tolerance(cls, a_amount: int, b_amount: int) -> bool:
        """Symmetric amount match.

        The window is derived from the LARGER magnitude of the two so the
        relation does not depend on which row happens to be scanned first — an
        order-dependent window made "are these duplicates?" answerable two
        different ways for the same pair of rows. No minimum floor: a 1-cent
        floor made every pair of zero-amount rows duplicates of each other, and
        made a 0 a duplicate of a real 1-cent transaction.
        """
        scale = max(abs(a_amount), abs(b_amount))
        tol = int(scale * cls.AMOUNT_TOLERANCE)
        return abs(a_amount - b_amount) <= tol

    @classmethod
    async def run(
        cls,
        db: AsyncSession,
        family_id: UUID,
        deleted_by_id: Optional[UUID] = None,
        dry_run: bool = False,
    ) -> dict:
        """Find and merge all duplicate groups for the family.

        Returns:
            {merged, refused, pairs, dry_run} — ``merged`` is the number of rows
            actually soft-deleted (0 on a dry run), ``pairs`` has one entry per
            row that was (or would be) removed, and ``refused`` counts groups
            left alone because several members carry receipt images.
        """
        stmt = (
            select(BudgetTransaction)
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
                # Split children are not standalone money; split parents carry
                # child legs whose categories differ, so merging them on amount
                # alone would strand those legs live in every activity total
                # while hiding the parent from the ledger.
                BudgetTransaction.parent_id.is_(None),
                BudgetTransaction.is_parent.is_(False),
            )
            .order_by(
                BudgetTransaction.date,
                BudgetTransaction.account_id,
                BudgetTransaction.created_at,
            )
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

        consumed: set[UUID] = set()
        merged = 0
        refused = 0
        pairs: list[dict] = []

        for i, anchor in enumerate(rows):
            if anchor.id in consumed:
                continue

            group = [anchor]
            for other in rows[i + 1:]:
                if other.id in consumed:
                    continue
                # Rows are ordered by date — once past this date, stop scanning.
                if other.date != anchor.date:
                    break
                # Same account only (same card/account means same purchase).
                if other.account_id != anchor.account_id:
                    continue
                if not cls._within_tolerance(int(anchor.amount), int(other.amount)):
                    continue
                group.append(other)

            if len(group) < 2:
                continue

            # Safety: several receipt images in one group means these are
            # plausibly distinct purchases of the same amount on the same day.
            # Refuse the whole group rather than guess which image belongs to
            # which purchase.
            if sum(1 for m in group if m.receipt_image_path) > 1:
                refused += 1
                # Consume the members so a later anchor cannot re-form a subset
                # of this group and merge rows we just refused to touch.
                consumed.update(m.id for m in group)
                logger.info(
                    "dedup: refusing group of %d on %s — multiple receipt images",
                    len(group), anchor.date,
                )
                continue

            scored = sorted(
                group,
                key=lambda t: (_score(t, item_counts.get(t.id, 0)), t.created_at),
                reverse=True,
            )
            keeper, losers = scored[0], scored[1:]
            consumed.update(m.id for m in group)

            keeper_score = _score(keeper, item_counts.get(keeper.id, 0))
            for loser in losers:
                pairs.append({
                    "keeper_id": str(keeper.id),
                    "loser_id": str(loser.id),
                    "keeper_score": keeper_score,
                    "loser_score": _score(loser, item_counts.get(loser.id, 0)),
                    "date": str(anchor.date),
                    "amount_cents": int(loser.amount),
                })
                if not dry_run:
                    await cls._merge(db, keeper, loser, deleted_by_id)
                    merged += 1

        if not dry_run and merged > 0:
            await db.commit()

        return {
            "merged": merged,
            "refused": refused,
            "pairs": pairs,
            "dry_run": dry_run,
        }

    @classmethod
    async def _merge(
        cls,
        db: AsyncSession,
        keeper: BudgetTransaction,
        loser: BudgetTransaction,
        deleted_by_id: Optional[UUID],
    ) -> None:
        # MOVE (do not copy) the image, so exactly one live row ever references
        # a stored object. A copy left both rows pointing at one file, and the
        # object key is named after the uploading transaction — so purging the
        # loser would eventually take the keeper's receipt with it.
        if loser.receipt_image_path and not keeper.receipt_image_path:
            keeper.receipt_image_path = loser.receipt_image_path
            loser.receipt_image_path = None

        # Never overwrite a note the user may have typed: fill when empty,
        # otherwise append. (The old rule kept whichever note was LONGER, which
        # silently destroyed short hand-written notes in favour of long
        # auto-imported bank memos, with no copy left anywhere.)
        loser_notes = (loser.notes or "").strip()
        if loser_notes:
            keeper_notes = (keeper.notes or "").strip()
            if not keeper_notes:
                keeper.notes = loser_notes
            elif loser_notes not in keeper_notes:
                keeper.notes = f"{keeper_notes}\n{loser_notes}"

        # Inherit category if keeper has none.
        if loser.category_id and not keeper.category_id:
            keeper.category_id = loser.category_id

        # Soft-delete the loser.
        loser.deleted_at = datetime.now(timezone.utc)
        loser.deleted_by_id = deleted_by_id

        db.add(keeper)
        db.add(loser)
        logger.info(
            "dedup: kept %s, removed %s | date=%s amt=%s",
            keeper.id, loser.id, keeper.date, keeper.amount,
        )
