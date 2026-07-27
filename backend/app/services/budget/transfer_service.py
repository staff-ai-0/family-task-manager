"""
Transfer Service

Business logic for transferring money between accounts and categories.
"""

# Aliased: transfer_between_accounts takes a `date: str` parameter that would
# otherwise shadow the class inside that function's body.
from datetime import date as date_cls
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetTransaction,
)
from app.services.budget.month_locking_service import MonthLockingService


class TransferService:
    """Service for handling account and category transfers"""
    
    @staticmethod
    async def transfer_between_accounts(
        db: AsyncSession,
        family_id: UUID,
        from_account_id: UUID,
        to_account_id: UUID,
        amount: int,
        date: str,
        notes: str | None = None,
        user_id: Optional[UUID] = None,
    ) -> List[BudgetTransaction]:
        """
        Transfer money between two accounts.
        
        Creates two linked transactions:
        - Negative transaction in source account (withdrawal)
        - Positive transaction in destination account (deposit)
        
        Args:
            db: Database session
            family_id: Family ID
            from_account_id: Source account
            to_account_id: Destination account
            amount: Amount to transfer in cents (positive)
            date: Transfer date (YYYY-MM-DD)
            notes: Optional notes
        
        Returns:
            List of two created transactions
        """
        # Defence in depth: the route schema enforces gt=0, but the service is
        # a public entry point for anything that does not go through it (Jarvis
        # MCP tools call services directly). A negative amount silently REVERSES
        # the transfer; zero writes two junk rows.
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transfer amount must be greater than zero",
            )
        if from_account_id == to_account_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transfer to the same account",
            )

        # Validate accounts exist and belong to family
        from_account_result = await db.execute(
            select(BudgetAccount).where(
                and_(
                    BudgetAccount.id == from_account_id,
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
        )
        from_account = from_account_result.scalar_one_or_none()
        if not from_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source account not found"
            )
        
        to_account_result = await db.execute(
            select(BudgetAccount).where(
                and_(
                    BudgetAccount.id == to_account_id,
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
        )
        to_account = to_account_result.scalar_one_or_none()
        if not to_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination account not found"
            )
        
        # A closed account is excluded from every balance total, so moving money
        # into one makes it vanish from the budget.
        for account, label in ((from_account, "Source"), (to_account, "Destination")):
            if account.closed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{label} account is closed",
                )

        # Parse date
        try:
            transfer_date = datetime.strptime(date, "%Y-%m-%d").date()  # noqa: DTZ007 — date-only parse, tz irrelevant
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD"
            )

        # Closing a month is meant to freeze it; every other write path honours
        # this, so transfers must not be a back door into a closed month.
        await MonthLockingService.validate_month_not_closed(
            db, family_id, date_cls(transfer_date.year, transfer_date.month, 1)
        )

        # Shared id so the two legs can be found and handled as one unit.
        pair_id = uuid4()
        
        # Create transfer note
        transfer_notes = notes or f"Transfer from {from_account.name} to {to_account.name}"
        
        # Create withdrawal transaction (negative amount)
        withdrawal = BudgetTransaction(
            id=uuid4(),
            family_id=family_id,
            account_id=from_account_id,
            date=transfer_date,
            amount=-amount,  # Negative for withdrawal
            notes=transfer_notes,
            transfer_account_id=to_account_id,
            transfer_pair_id=pair_id,
            cleared=True,  # Transfers are auto-cleared
            created_by_id=user_id,
        )
        db.add(withdrawal)

        # Create deposit transaction (positive amount)
        deposit = BudgetTransaction(
            id=uuid4(),
            family_id=family_id,
            account_id=to_account_id,
            date=transfer_date,
            amount=amount,  # Positive for deposit
            notes=transfer_notes,
            transfer_account_id=from_account_id,
            transfer_pair_id=pair_id,
            cleared=True,  # Transfers are auto-cleared
            created_by_id=user_id,
        )
        db.add(deposit)
        
        await db.flush()
        await db.commit()
        await db.refresh(withdrawal)
        await db.refresh(deposit)
        
        return [withdrawal, deposit]
    
    @staticmethod
    async def transfer_between_categories(
        db: AsyncSession,
        family_id: UUID,
        from_category_id: UUID,
        to_category_id: UUID,
        amount: int,
        month: str,
        notes: str | None = None,
    ) -> dict:
        """
        Transfer budgeted money between categories.
        
        This adjusts the budget allocations for the specified month,
        moving money from one category to another without creating transactions.
        
        Args:
            db: Database session
            family_id: Family ID
            from_category_id: Source category
            to_category_id: Destination category
            amount: Amount to transfer in cents (positive)
            month: Month (YYYY-MM-DD, first day of month)
            notes: Optional notes
        
        Returns:
            Dict with updated allocations
        """
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transfer amount must be greater than zero",
            )
        if from_category_id == to_category_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transfer to the same category",
            )

        # Validate categories exist and belong to family
        from_category_result = await db.execute(
            select(BudgetCategory).where(
                and_(
                    BudgetCategory.id == from_category_id,
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.deleted_at.is_(None),
                )
            )
        )
        from_category = from_category_result.scalar_one_or_none()
        if not from_category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source category not found"
            )
        
        to_category_result = await db.execute(
            select(BudgetCategory).where(
                and_(
                    BudgetCategory.id == to_category_id,
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.deleted_at.is_(None),
                )
            )
        )
        to_category = to_category_result.scalar_one_or_none()
        if not to_category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination category not found"
            )
        
        # Ready-to-Assign counts only EXPENSE budgeted amounts, so moving money
        # into an income category un-assigns it with no audit trail (and out of
        # one conjures assignable money from nothing).
        group_ids = [from_category.group_id, to_category.group_id]
        income_groups = (
            await db.execute(
                select(BudgetCategoryGroup.id).where(
                    BudgetCategoryGroup.id.in_(group_ids),
                    BudgetCategoryGroup.is_income.is_(True),
                )
            )
        ).scalars().all()
        if income_groups:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot transfer budgeted money to or from an income category",
            )

        # Parse month
        try:
            month_date = datetime.strptime(month, "%Y-%m-%d").date()  # noqa: DTZ007 — date-only parse, tz irrelevant
            # Ensure it's first day of month
            month_date = date_cls(month_date.year, month_date.month, 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid month format. Use YYYY-MM-DD"
            )

        await MonthLockingService.validate_month_not_closed(
            db, family_id, month_date
        )

        # Get or create source allocation
        from_allocation_result = await db.execute(
            select(BudgetAllocation).where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.category_id == from_category_id,
                    BudgetAllocation.month == month_date
                )
            )
        )
        from_allocation = from_allocation_result.scalar_one_or_none()
        if not from_allocation:
            from_allocation = BudgetAllocation(
                id=uuid4(),
                family_id=family_id,
                category_id=from_category_id,
                month=month_date,
                budgeted_amount=0,
            )
            db.add(from_allocation)
        
        # Guard on the envelope's AVAILABLE amount, not on what was budgeted this
        # month. Budgeted ignores both spending and rollover, so the old check
        # let an already-spent envelope be emptied again (manufacturing an
        # overspend out of nothing) while refusing to move money a category had
        # genuinely carried over — the exact figure the UI shows the user.
        from app.services.budget.allocation_service import AllocationService

        source_state = await AllocationService.get_category_available_amount(
            db, family_id, from_category_id, month_date
        )
        source_available = int(source_state["available"])
        if source_available < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Insufficient funds in source category. "
                    f"Available: ${source_available/100:.2f}, "
                    f"Requested: ${amount/100:.2f}"
                ),
            )
        
        # Get or create destination allocation
        to_allocation_result = await db.execute(
            select(BudgetAllocation).where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.category_id == to_category_id,
                    BudgetAllocation.month == month_date
                )
            )
        )
        to_allocation = to_allocation_result.scalar_one_or_none()
        if not to_allocation:
            to_allocation = BudgetAllocation(
                id=uuid4(),
                family_id=family_id,
                category_id=to_category_id,
                month=month_date,
                budgeted_amount=0,
            )
            db.add(to_allocation)
        
        # Perform transfer
        from_allocation.budgeted_amount -= amount
        to_allocation.budgeted_amount += amount
        
        # Update notes if provided
        transfer_note = notes or f"Transfer from {from_category.name}"
        if to_allocation.notes:
            to_allocation.notes += f"\n{transfer_note}"
        else:
            to_allocation.notes = transfer_note
        
        await db.commit()
        await db.refresh(from_allocation)
        await db.refresh(to_allocation)
        
        return {
            "from_category": {
                "id": str(from_category_id),
                "name": from_category.name,
                "budgeted": from_allocation.budgeted_amount,
            },
            "to_category": {
                "id": str(to_category_id),
                "name": to_category.name,
                "budgeted": to_allocation.budgeted_amount,
            },
            "amount_transferred": amount,
        }
