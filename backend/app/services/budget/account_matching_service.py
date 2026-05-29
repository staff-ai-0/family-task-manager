"""Pick a target account for a scanned receipt.

Strategy order:
1. Caller-supplied account_id (validated to belong to family) → strategy="override"
2. Match BudgetAccount.card_last4 → narrow by receipt currency if >1  → strategy="card_last4"
3. Most-recent transaction in the family (any user) → strategy="last_used"
   NOTE: BudgetTransaction has no created_by_id / user_id column as of the
   current schema, so per-user disambiguation is not possible.
   TODO: add created_by_id to budget_transactions and introduce a
   per-user step between card_last4 and the family-wide fallback.
4. None → strategy="none"
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetAccount, BudgetTransaction


@dataclass
class AccountMatchResult:
    account_id: Optional[UUID]
    strategy: str  # "card_last4" | "last_used" | "override" | "none"
    matched_card_last4: Optional[str] = field(default=None)
    matched_account_currency: Optional[str] = field(default=None)


class AccountMatchingService:

    @staticmethod
    async def match(
        db: AsyncSession,
        family_id: UUID,
        user_id: UUID,
        card_last4: Optional[str],
        receipt_currency: Optional[str],
        override_account_id: Optional[UUID] = None,
    ) -> AccountMatchResult:
        """Return the best account match for a scanned receipt.

        Parameters
        ----------
        db:                  Async SQLAlchemy session.
        family_id:           Tenant scope — all queries are filtered by this.
        user_id:             Authenticated user (reserved for future per-user
                             last-used step once created_by_id is added to
                             budget_transactions).
        card_last4:          4-digit suffix extracted from the receipt by the
                             vision model, or None.
        receipt_currency:    ISO-4217 currency detected on the receipt (used
                             to disambiguate when multiple accounts share the
                             same card_last4), or None.
        override_account_id: Explicit account chosen by the caller; validated
                             for ownership before accepting.

        NOTE: an `override_account_id` that does NOT belong to ``family_id``
        is silently ignored — the method falls through to the next strategy
        rather than raising. Callers are expected to pre-validate ownership
        of an explicit override (the scan-receipt endpoint does this via
        ``AccountService.get_by_id``).
        """

        # --- Strategy 1: caller override ----------------------------------------
        if override_account_id is not None:
            stmt = select(BudgetAccount).where(and_(
                BudgetAccount.id == override_account_id,
                BudgetAccount.family_id == family_id,
            ))
            row = (await db.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return AccountMatchResult(
                    account_id=row.id,
                    strategy="override",
                    matched_account_currency=row.currency,
                )

        # --- Strategy 2: card_last4 match ---------------------------------------
        if card_last4:
            stmt = select(BudgetAccount).where(and_(
                BudgetAccount.family_id == family_id,
                BudgetAccount.card_last4 == card_last4,
                BudgetAccount.closed.is_(False),
                BudgetAccount.deleted_at.is_(None),
            ))
            hits = list((await db.execute(stmt)).scalars().all())

            if len(hits) == 1:
                return AccountMatchResult(
                    account_id=hits[0].id,
                    strategy="card_last4",
                    matched_card_last4=card_last4,
                    matched_account_currency=hits[0].currency,
                )

            if len(hits) > 1 and receipt_currency:
                by_ccy = [h for h in hits
                          if h.currency == receipt_currency.upper()]
                if len(by_ccy) == 1:
                    return AccountMatchResult(
                        account_id=by_ccy[0].id,
                        strategy="card_last4",
                        matched_card_last4=card_last4,
                        matched_account_currency=by_ccy[0].currency,
                    )

        # --- Strategy 3: most-recent transaction in family ----------------------
        # Per-user narrowing is intentionally skipped here because
        # BudgetTransaction.created_by_id does not exist yet.
        # TODO: once created_by_id is added, insert a per-user step before
        # this family-wide fallback.
        stmt = (
            select(BudgetTransaction.account_id, BudgetAccount.currency)
            .join(BudgetAccount, BudgetAccount.id == BudgetTransaction.account_id)
            .where(and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
                BudgetAccount.deleted_at.is_(None),
                BudgetAccount.closed.is_(False),
            ))
            .order_by(desc(BudgetTransaction.created_at))
            .limit(1)
        )
        result = (await db.execute(stmt)).first()
        if result:
            return AccountMatchResult(
                account_id=result[0],
                strategy="last_used",
                matched_account_currency=result[1],
            )

        # --- Strategy 4: nothing ------------------------------------------------
        return AccountMatchResult(account_id=None, strategy="none")
