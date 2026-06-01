"""Detect inter-account transfers from payee/notes text.

Bank-statement imports carry rows like "Transferencia a BBVA MEXICO", card
payments, and ATM withdrawals. These are not spending — they move money around
the user's own accounts (or pull cash). We bucket them into the family's
"Transferencias" group so they stay organized and are excluded from spending
and income reports.

Detection runs FIRST in the categorization precedence chain (before rule,
payee-default, AI) — a transfer is a transfer regardless of merchant rules.
"""

import re
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetCategory, BudgetCategoryGroup

# Category name (within the Transferencias group) → ordered regex patterns.
# Patterns are matched case-insensitively against "payee \n notes". First
# category whose any pattern hits wins; order matters (card payment before the
# generic transfer catch-all).
_TRANSFER_RULES: list[tuple[str, list[str]]] = [
    ("Pago de Tarjeta", [
        r"pago\s+(de\s+|a\s+)?tarjeta", r"pago\s+tdc", r"pago\s+t\.?d\.?c",
        r"pago\s+(de\s+)?cr[eé]dito", r"domiciliaci[oó]n\s+tarjeta",
    ]),
    ("Retiro de Efectivo", [
        r"cajero", r"retiro\s+(de\s+)?efectivo", r"disposici[oó]n\s+(de\s+)?efectivo",
        r"\batm\b", r"retiro\s+en\b",
    ]),
    ("Entre Cuentas", [
        r"transferencia", r"traspaso", r"\bspei\b", r"\btransfer\b",
        r"env[ií]o\s+a\s+cuenta", r"dep[oó]sito\s+a\s+cuenta",
    ]),
]


def detect_transfer_category_name(*texts: Optional[str]) -> Optional[str]:
    """Return the transfer category NAME for the given text(s), or None.

    Pass any combination of payee name + notes; they're concatenated and
    matched. None means "not a transfer" — let normal categorization proceed.
    """
    blob = " \n ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for cat_name, patterns in _TRANSFER_RULES:
        for pat in patterns:
            if re.search(pat, blob):
                return cat_name
    return None


# Bank-alert "kind" (classified by the email-matcher LLM) → transfer category.
# Lets the matcher agent classify the email TYPE directly (a far better signal
# than regex over a truncated merchant string like "BBVA MEXICO").
KIND_TO_TRANSFER_CATEGORY: dict[str, str] = {
    "transfer": "Entre Cuentas",
    "withdrawal": "Retiro de Efectivo",
    "card_payment": "Pago de Tarjeta",
}


async def _transfer_categories(db: AsyncSession, family_id: UUID) -> list[tuple]:
    return (await db.execute(
        select(BudgetCategory.id, BudgetCategory.name)
        .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
        .where(
            BudgetCategory.family_id == family_id,
            BudgetCategory.deleted_at.is_(None),
            BudgetCategoryGroup.is_transfer.is_(True),
            BudgetCategoryGroup.deleted_at.is_(None),
        )
    )).all()


async def resolve_transfer_category_by_name(
    db: AsyncSession, family_id: UUID, name: str,
) -> Optional[UUID]:
    """Map a transfer category NAME to its id in the family's transfer group.
    Falls back to any category in the transfer group. None if no group."""
    rows = await _transfer_categories(db, family_id)
    if not rows:
        return None
    by_name = {r[1].lower(): r[0] for r in rows}
    return by_name.get(name.lower()) or rows[0][0]


async def resolve_transfer_category_for_kind(
    db: AsyncSession, family_id: UUID, kind: Optional[str],
) -> Optional[UUID]:
    """Resolve a transfer category from an email-matcher `kind`. None when the
    kind isn't a transfer type (purchase/deposit/refund/fee/other → normal flow)."""
    name = KIND_TO_TRANSFER_CATEGORY.get((kind or "").lower())
    if name is None:
        return None
    return await resolve_transfer_category_by_name(db, family_id, name)


async def resolve_transfer_category_id(
    db: AsyncSession,
    family_id: UUID,
    *texts: Optional[str],
) -> Optional[UUID]:
    """Detect a transfer from free text and map it to a concrete category_id in
    the family's transfer group. Falls back to any category in the transfer
    group when the specific name is missing. None when the text isn't a transfer
    or the family has no transfer group yet.
    """
    name = detect_transfer_category_name(*texts)
    if name is None:
        return None
    return await resolve_transfer_category_by_name(db, family_id, name)
