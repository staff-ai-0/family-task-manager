"""AI-assisted transaction categorization.

Actual Budget solves categorization with rules + payee-learning, which both
start empty (cold-start = everything uncategorized until taught). This service
adds the lever Actual lacks: an LLM that already understands that
"PETRO 7 PETROMAX / MAGNA" is gasoline and "Mei Laii ASIAN BUFFET" is a
restaurant. Given the family's own category list it picks the best fit.

Used as the LAST resort in the precedence chain
    explicit rule  >  payee.default_category  >  AI suggestion  >  uncategorized
so the (cheap, but non-zero) LLM call is skipped whenever a rule or a learned
payee default already answers.

Routes through the same LiteLLM proxy as the receipt scanner. Text-only and
tiny output, so it is fast and cheap. Returns None on any failure — callers
must treat categorization as best-effort.
"""

import json
import logging
import os
import re
from typing import Optional
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.budget import BudgetCategory, BudgetCategoryGroup, BudgetPayee, BudgetTransaction

logger = logging.getLogger(__name__)

CATEGORIZER_MODEL = os.environ.get("CATEGORIZER_MODEL", "gemini-2.5-flash")


class CategoryAIService:

    @staticmethod
    async def _load_categories(
        db: AsyncSession, family_id: UUID, *, is_income: bool
    ) -> list[tuple[UUID, str]]:
        """Return [(category_id, "Group > Category")] for the income/expense
        side, excluding hidden + soft-deleted rows. Ordered for stable prompts."""
        rows = (await db.execute(
            select(
                BudgetCategory.id,
                BudgetCategory.name,
                BudgetCategoryGroup.name,
            )
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                BudgetCategory.family_id == family_id,
                BudgetCategory.deleted_at.is_(None),
                BudgetCategory.hidden.is_(False),
                BudgetCategoryGroup.deleted_at.is_(None),
                BudgetCategoryGroup.hidden.is_(False),
                BudgetCategoryGroup.is_income.is_(is_income),
            )
            .order_by(BudgetCategoryGroup.sort_order, BudgetCategory.sort_order)
        )).all()
        return [(r[0], f"{r[2]} > {r[1]}") for r in rows]

    @classmethod
    async def suggest(
        cls,
        db: AsyncSession,
        family_id: UUID,
        payee_name: Optional[str],
        item_names: Optional[list[str]] = None,
        *,
        is_income: bool = False,
        cache: Optional[dict] = None,
    ) -> Optional[UUID]:
        """Suggest a category_id for a purchase. None if no good fit / on error.

        `cache` is an optional dict keyed by lowercased payee name; pass one
        across a batch (e.g. backfill) so the same merchant isn't queried twice.
        """
        if not payee_name and not item_names:
            return None
        if not settings.LITELLM_API_KEY:
            return None

        cache_key = (payee_name or "").strip().lower()
        if cache is not None and cache_key and cache_key in cache:
            return cache[cache_key]

        cats = await cls._load_categories(db, family_id, is_income=is_income)
        if not cats:
            return None

        numbered = "\n".join(f"{i + 1}. {label}" for i, (_, label) in enumerate(cats))
        items_str = ""
        if item_names:
            clean = [str(n).strip() for n in item_names if n and str(n).strip()]
            if clean:
                items_str = "\nArtículos: " + ", ".join(clean[:20])

        prompt = (
            "Eres un asistente de presupuesto familiar en México. Clasifica esta "
            "compra en UNA sola categoría de la lista, eligiendo el mejor ajuste.\n"
            f"Comercio: {payee_name or '(desconocido)'}{items_str}\n\n"
            f"Categorías:\n{numbered}\n\n"
            'Responde SOLO JSON: {"index": N} con el número de la mejor categoría, '
            'o {"index": null} si ninguna aplica con claridad.'
        )

        try:
            client = OpenAI(
                base_url=f"{settings.LITELLM_API_BASE.rstrip('/')}/v1",
                api_key=settings.LITELLM_API_KEY,
            )
            completion = client.chat.completions.create(
                model=CATEGORIZER_MODEL,
                max_tokens=50,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
                extra_body={"thinking_config": {"thinking_budget": 0}},
            )
            text = (completion.choices[0].message.content or "").strip()
        except Exception:
            logger.exception("category AI call failed for payee=%s", payee_name)
            return None

        result: Optional[UUID] = None
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                idx = json.loads(m.group()).get("index")
                if isinstance(idx, int) and 1 <= idx <= len(cats):
                    result = cats[idx - 1][0]
            except (json.JSONDecodeError, TypeError, ValueError):
                result = None

        if cache is not None and cache_key:
            cache[cache_key] = result
        return result

    @classmethod
    async def backfill(cls, db: AsyncSession, family_id: UUID) -> dict:
        """Categorize all uncategorized transactions for a family.

        Precedence per transaction: payee.default_category → AI suggestion.
        Learns: when AI assigns a category and the payee has no default yet,
        the payee's default_category is set so future scans/imports skip the AI.

        Returns {scanned, applied}.
        """
        # Make sure the family has a transfer bucket before we start labeling.
        from app.services.budget.default_categories import ensure_transfer_group
        from app.services.budget.transfer_detector import resolve_transfer_category_id
        await ensure_transfer_group(db, family_id)

        rows = (await db.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.category_id.is_(None),
                BudgetTransaction.deleted_at.is_(None),
                BudgetTransaction.parent_id.is_(None),
            )
        )).scalars().all()

        cache: dict = {}
        payee_cache: dict[UUID, BudgetPayee] = {}
        applied = 0

        for txn in rows:
            payee: Optional[BudgetPayee] = None
            if txn.payee_id:
                payee = payee_cache.get(txn.payee_id)
                if payee is None:
                    payee = await db.get(BudgetPayee, txn.payee_id)
                    if payee is not None:
                        payee_cache[txn.payee_id] = payee

            cat: Optional[UUID] = None
            # Transfer detection first — keeps non-spending rows out of the AI.
            cat = await resolve_transfer_category_id(
                db, family_id, payee.name if payee else None, txn.notes,
            )
            if cat is None and payee and payee.default_category_id:
                cat = payee.default_category_id
            if cat is None:
                cat = await cls.suggest(
                    db, family_id,
                    payee.name if payee else None,
                    is_income=txn.amount > 0,
                    cache=cache,
                )

            if cat is not None:
                txn.category_id = cat
                applied += 1
                if payee is not None and not payee.default_category_id:
                    payee.default_category_id = cat

        await db.commit()
        logger.info("backfill categorized %d/%d txns for family %s", applied, len(rows), family_id)
        return {"scanned": len(rows), "applied": applied}
