"""CashService — cash currency ledger (centavos). Gigs credit; parents pay out.

Symmetric with PointsService but a separate balance (User.cash_cents) and
ledger (cash_transactions). Cash never converts to/from points. See
docs/superpowers/specs/2026-06-30-two-currency-economy-design.md.
"""
from uuid import UUID
from typing import Optional, List

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.core.exceptions import ValidationException
from app.services.base_service import get_user_by_id


class CashService:
    """Service for cash-related operations (centavos)."""

    @staticmethod
    async def get_balance(db: AsyncSession, user_id: UUID) -> int:
        user = await get_user_by_id(db, user_id)
        return user.cash_cents

    @staticmethod
    async def award_gig_cash(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        assignment_id: Optional[UUID],
        amount_cents: int,
        description: Optional[str] = None,
        gig_claim_id: Optional[UUID] = None,
    ) -> CashTransaction:
        """Credit (or claw back, if negative) gig-board cash. Caller commits.

        Mirrors PointsService.award_gig_points: no commit, so it composes
        inside the gig-approval transaction. Link the source via either
        ``assignment_id`` or ``gig_claim_id`` (gig board uses the latter).
        """
        user = await get_user_by_id(db, user_id)
        before = user.cash_cents
        tx = CashTransaction(
            type=CashTransactionType.GIG_EARNED,
            user_id=user_id,
            family_id=family_id,
            assignment_id=assignment_id,
            gig_claim_id=gig_claim_id,
            amount_cents=amount_cents,
            balance_before=before,
            balance_after=before + amount_cents,
            description=description or f"Gig — ${amount_cents / 100:.2f} MXN",
        )
        user.cash_cents = before + amount_cents
        db.add(tx)
        return tx

    @staticmethod
    async def record_payout(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        created_by: UUID,
    ) -> CashTransaction:
        """Parent records a payout (full or partial). Debits cash_cents."""
        if amount_cents <= 0:
            raise ValidationException("Payout amount must be positive")
        user = await get_user_by_id(db, user_id)
        if amount_cents > user.cash_cents:
            raise ValidationException(
                f"Payout exceeds balance. Balance ${user.cash_cents / 100:.2f}, "
                f"requested ${amount_cents / 100:.2f}"
            )
        before = user.cash_cents
        tx = CashTransaction(
            type=CashTransactionType.PAYOUT,
            user_id=user_id,
            family_id=family_id,
            amount_cents=-amount_cents,
            balance_before=before,
            balance_after=before - amount_cents,
            created_by=created_by,
            description=f"Paid ${amount_cents / 100:.2f} MXN",
        )
        user.cash_cents = before - amount_cents
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def adjust(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        reason: str,
        created_by: UUID,
    ) -> CashTransaction:
        """Manual signed cash adjustment by a parent. Floors balance at 0."""
        user = await get_user_by_id(db, user_id)
        before = user.cash_cents
        after = before + amount_cents
        if after < 0:
            after = 0
            amount_cents = -before
        tx = CashTransaction(
            type=CashTransactionType.ADJUSTMENT,
            user_id=user_id,
            family_id=family_id,
            amount_cents=amount_cents,
            balance_before=before,
            balance_after=after,
            created_by=created_by,
            description=reason,
        )
        user.cash_cents = after
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def get_history(
        db: AsyncSession, user_id: UUID, limit: int = 50
    ) -> List[CashTransaction]:
        q = (
            select(CashTransaction)
            .where(CashTransaction.user_id == user_id)
            .order_by(CashTransaction.created_at.desc())
            .limit(limit)
        )
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def get_summary(db: AsyncSession, user_id: UUID) -> dict:
        user = await get_user_by_id(db, user_id)
        earned = (
            await db.execute(
                select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                    and_(
                        CashTransaction.user_id == user_id,
                        CashTransaction.amount_cents > 0,
                    )
                )
            )
        ).scalar() or 0
        paid = (
            await db.execute(
                select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                    and_(
                        CashTransaction.user_id == user_id,
                        CashTransaction.type == CashTransactionType.PAYOUT,
                    )
                )
            )
        ).scalar() or 0
        return {
            "current_balance": int(user.cash_cents),
            "total_earned": int(earned),
            "total_paid": int(abs(paid)),
        }
