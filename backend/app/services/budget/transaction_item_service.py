"""Transaction item CRUD + price-trend lookup.

Items are first-class child rows of a BudgetTransaction. They power:
- per-item categorization
- price-trend badges on the confirm card
- the a2a webhook payload to the external price-comparison agent
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetTransactionItem
from app.schemas.budget import ItemTrend


_LEADING_QTY_RE = re.compile(r"^\s*\d+\s*(?:x|pza|pzas|pieza|piezas)?\s+", re.IGNORECASE)
# Strips trailing "500g", "1L", "2 kg" etc. (with leading digit)
_TRAILING_UNIT_RE = re.compile(
    r"\s*\b\d+\s*(?:kg|g|lt|l|ml|pza|pzas)\b\s*$", re.IGNORECASE
)
# Strips trailing bare unit words with no digit, e.g. " kg", " lt", " g"
_TRAILING_BARE_UNIT_RE = re.compile(
    r"\s+\b(?:kg|g|lt|l|ml|pza|pzas)\b\s*$", re.IGNORECASE
)
_UNIT_SUFFIX_RE = re.compile(
    r"\s*\b(\d+\s*(?:kg|g|lt|l|ml|pza|pzas|pieza|piezas|pkg|pack))\b\s*",
    flags=re.IGNORECASE,
)


def normalize_name(raw: str) -> str:
    """Lowercase, strip accents, strip unit suffixes + leading quantities."""
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _LEADING_QTY_RE.sub("", s)
    s = _TRAILING_UNIT_RE.sub("", s)
    s = _TRAILING_BARE_UNIT_RE.sub("", s)
    s = _UNIT_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class TransactionItemService:

    @staticmethod
    async def bulk_create(
        db: AsyncSession,
        family_id: UUID,
        transaction_id: UUID,
        items: list[dict],
    ) -> list[BudgetTransactionItem]:
        """Insert a batch of items as children of a transaction.

        The caller owns the transaction lifecycle — this method only
        ``db.add()``s rows and ``db.flush()``es to populate server-default
        primary keys. It does NOT commit and does NOT refresh, which keeps
        the unit of work intact across the scanner pipeline (transaction
        header, items, categorization all commit together). Server-default
        timestamps like ``created_at`` are NOT populated on the returned
        Python objects — callers that need them must ``db.refresh()`` the
        rows themselves after their own commit.
        """
        rows: list[BudgetTransactionItem] = []
        for it in items:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            row = BudgetTransactionItem(
                family_id=family_id,
                transaction_id=transaction_id,
                name=name,
                normalized_name=normalize_name(name),
                qty=it.get("qty"),
                unit_price_cents=it.get("unit_price_cents"),
                total_cents=int(it.get("total_cents") or 0),
                category_id=it.get("category_id"),
                brand=it.get("brand"),
                raw_text=it.get("raw_text"),
            )
            db.add(row)
            rows.append(row)
        # Populate id from gen_random_uuid() default without committing —
        # the scanner pipeline still needs to assign category_id per row
        # and wants a single atomic commit.
        await db.flush()
        return rows

    @staticmethod
    async def list_for_family(
        db: AsyncSession,
        family_id: UUID,
        normalized_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BudgetTransactionItem]:
        stmt = select(BudgetTransactionItem).where(
            BudgetTransactionItem.family_id == family_id
        )
        if normalized_name:
            stmt = stmt.where(BudgetTransactionItem.normalized_name == normalized_name)
        if since:
            stmt = stmt.where(BudgetTransactionItem.created_at >= since)
        stmt = stmt.order_by(desc(BudgetTransactionItem.created_at)).limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_trend(
        db: AsyncSession,
        family_id: UUID,
        normalized_name: str,
        window_days: int = 90,
        min_sample: int = 3,
    ) -> Optional[ItemTrend]:
        """Return price trend for an item over the last window_days.

        avg_unit_cents = mean of all PRIOR items (excludes the most recent)
        last_unit_cents = the most recent item's unit_price_cents
        pct_change = (last - avg) / avg
        Returns None when sample_size < min_sample OR no priors with unit_price_cents.
        """
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        stmt = (
            select(BudgetTransactionItem)
            .where(and_(
                BudgetTransactionItem.family_id == family_id,
                BudgetTransactionItem.normalized_name == normalized_name,
                BudgetTransactionItem.created_at >= since,
                BudgetTransactionItem.unit_price_cents.isnot(None),
            ))
            .order_by(desc(BudgetTransactionItem.created_at))
        )
        rows = list((await db.execute(stmt)).scalars().all())
        if len(rows) < min_sample:
            return None
        last = rows[0]
        priors = rows[1:]
        avg = sum(int(p.unit_price_cents) for p in priors) // len(priors)
        if avg == 0:
            return None
        last_v = int(last.unit_price_cents)
        pct = (last_v - avg) / avg
        return ItemTrend(
            normalized_name=normalized_name,
            avg_unit_cents=avg,
            last_unit_cents=last_v,
            pct_change=round(pct, 4),
            sample_size=len(rows),
        )
