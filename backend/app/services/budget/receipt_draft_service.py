"""
Receipt Draft Service — HITL review queue for low-confidence receipt scans.

When the vision model cannot extract data with sufficient confidence,
scan_and_create_transaction creates a BudgetReceiptDraft instead of
discarding the result. A parent then reviews, edits, and approves or
rejects the draft from the UI.
"""

from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationException
from app.models.budget import BudgetPayee, BudgetReceiptDraft
from app.schemas.budget import ReceiptDraftApprove
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import TransactionCreate


class ReceiptDraftService:

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        account_id: UUID,
        scanned_data: dict,
        confidence: float,
    ) -> BudgetReceiptDraft:
        """Persist a low-confidence scan result for later human review."""
        draft = BudgetReceiptDraft(
            family_id=family_id,
            account_id=account_id,
            scanned_data=scanned_data,
            confidence=confidence,
            status="pending",
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        return draft

    @classmethod
    async def list_pending(
        cls, db: AsyncSession, family_id: UUID
    ) -> List[BudgetReceiptDraft]:
        """Return all pending drafts for a family, newest first."""
        stmt = (
            select(BudgetReceiptDraft)
            .where(
                BudgetReceiptDraft.family_id == family_id,
                BudgetReceiptDraft.status == "pending",
            )
            .order_by(BudgetReceiptDraft.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def get_by_id(
        cls, db: AsyncSession, draft_id: UUID, family_id: UUID
    ) -> BudgetReceiptDraft:
        stmt = select(BudgetReceiptDraft).where(
            BudgetReceiptDraft.id == draft_id,
            BudgetReceiptDraft.family_id == family_id,
        )
        result = await db.execute(stmt)
        draft = result.scalars().first()
        if not draft:
            raise NotFoundException(f"Receipt draft {draft_id} not found")
        return draft

    @classmethod
    async def pending_count(cls, db: AsyncSession, family_id: UUID) -> int:
        """Count pending drafts — used for the nav badge."""
        drafts = await cls.list_pending(db, family_id)
        return len(drafts)

    @classmethod
    async def approve(
        cls,
        db: AsyncSession,
        draft_id: UUID,
        family_id: UUID,
        overrides: ReceiptDraftApprove,
        user_id: Optional[UUID] = None,
    ) -> dict:
        """Approve a draft: apply human corrections, create the transaction.

        The human may override any of: date, amount, payee_name, category_id,
        notes. Fields left as None fall back to whatever the scanner extracted.
        """
        draft = await cls.get_by_id(db, draft_id, family_id)

        # Resolve the target account: explicit override wins; else the
        # account captured at scan time. Account-less drafts (family had no
        # accounts when scanning) REQUIRE the override.
        target_account_id = overrides.account_id or draft.account_id
        if target_account_id is None:
            raise ValidationException(
                "Elige una cuenta para aprobar este recibo / "
                "Pick an account to approve this receipt (account_id)"
            )
        if overrides.account_id is not None:
            # Validate family scope of the chosen account.
            from app.models.budget import BudgetAccount
            acct = (await db.execute(select(BudgetAccount).where(
                BudgetAccount.id == overrides.account_id,
                BudgetAccount.family_id == family_id,
            ))).scalars().first()
            if acct is None:
                raise ValidationException("Account not found in this family")

        sd = draft.scanned_data  # what the scanner saw

        # Resolve payee — use overridden name or extracted name
        payee_name = overrides.payee_name or sd.get("payee_name")
        payee_id: Optional[UUID] = None
        if payee_name:
            stmt = select(BudgetPayee).where(
                BudgetPayee.family_id == family_id,
                BudgetPayee.name == payee_name,
            )
            result = await db.execute(stmt)
            payee = result.scalars().first()
            if payee:
                payee_id = payee.id
            else:
                new_payee = BudgetPayee(family_id=family_id, name=payee_name)
                db.add(new_payee)
                await db.flush()
                payee_id = new_payee.id

        # Resolve amount and date
        amount = overrides.amount if overrides.amount is not None else sd.get("total_amount")
        if amount is None:
            amount = 0  # fallback — human should have filled this in

        txn_date = overrides.date
        if txn_date is None and sd.get("date"):
            try:
                txn_date = date.fromisoformat(sd["date"])
            except (ValueError, TypeError):
                pass
        txn_date = txn_date or date.today()

        notes = overrides.notes
        if notes is None:
            from app.services.budget.receipt_scanner_service import _build_notes
            notes = _build_notes(sd.get("payee_name"), sd.get("items", []), sd.get("currency", "MXN"))

        # Carry v2 scanner fields (card_last4, iva_cents) from the draft
        # through to the persisted transaction. FX fields are intentionally
        # NOT propagated: FX rate lookup happens at scan time, not at
        # draft-approval time, and the original FX context is gone by now.
        txn_data = TransactionCreate(
            account_id=target_account_id,
            date=txn_date,
            amount=amount,
            payee_id=payee_id,
            category_id=overrides.category_id,
            notes=notes,
            cleared=False,
            reconciled=False,
            card_last4=sd.get("card_last4"),
            iva_cents=sd.get("iva_cents"),
        )
        transaction = await TransactionService.create(
            db, family_id, txn_data, user_id=user_id,
        )

        # Mark draft approved
        draft.status = "approved"
        draft.transaction_id = transaction.id
        draft.reviewed_at = datetime.now(timezone.utc)
        await db.commit()

        return {
            "success": True,
            "transaction_id": str(transaction.id),
            "draft_id": str(draft.id),
        }

    @classmethod
    async def reject(
        cls, db: AsyncSession, draft_id: UUID, family_id: UUID
    ) -> None:
        """Mark a draft rejected — no transaction is created."""
        draft = await cls.get_by_id(db, draft_id, family_id)
        draft.status = "rejected"
        draft.reviewed_at = datetime.now(timezone.utc)
        await db.commit()
