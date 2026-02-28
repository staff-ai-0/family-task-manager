"""
Transfer Service

Business logic for transferring money between accounts and categories.
"""

from datetime import date, datetime
from typing import List
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import (
    BudgetAccount,
    BudgetAllocation,
    BudgetCategory,
    BudgetTransaction,
)


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
        # Validate accounts exist and belong to family
        from_account_result = await db.execute(
            select(BudgetAccount).where(
                and_(
                    BudgetAccount.id == from_account_id,
                    BudgetAccount.family_id == family_id
                )
            )
        )
        from_account = from_account_result.scalar_one_or_none()
        if not from_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source account not found"
            )
        
        to_account_result = await db.execute(
            select(BudgetAccount).where(
                and_(
                    BudgetAccount.id == to_account_id,
                    BudgetAccount.family_id == family_id
                )
            )
        )
        to_account = to_account_result.scalar_one_or_none()
        if not to_account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Destination account not found"
            )
        
        # Parse date
        try:
            transfer_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date format. Use YYYY-MM-DD"
            )
        
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
            cleared=True,  # Transfers are auto-cleared
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
            cleared=True,  # Transfers are auto-cleared
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
        # Validate categories exist and belong to family
        from_category_result = await db.execute(
            select(BudgetCategory).where(
                and_(
                    BudgetCategory.id == from_category_id,
                    BudgetCategory.family_id == family_id
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
                    BudgetCategory.family_id == family_id
                )
            )
        )
        to_category = to_category_result.scalar_one_or_none()
        if not to_category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Destination category not found"
            )
        
        # Parse month
        try:
            month_date = datetime.strptime(month, "%Y-%m-%d").date()
            # Ensure it's first day of month
            month_date = date(month_date.year, month_date.month, 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid month format. Use YYYY-MM-DD"
            )
        
        # Get or create source allocation
        from_allocation_result = await db.execute(
            select(BudgetAllocation).where(
                and_(
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
        
        # Check if source has enough budget
        if from_allocation.budgeted_amount < amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient budget in source category. Available: ${from_allocation.budgeted_amount/100:.2f}, Requested: ${amount/100:.2f}"
            )
        
        # Get or create destination allocation
        to_allocation_result = await db.execute(
            select(BudgetAllocation).where(
                and_(
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
    
    @staticmethod
    async def cover_overspending(
        db: AsyncSession,
        family_id: UUID,
        overspent_category_id: UUID,
        source_category_id: UUID,
        month: str,
    ) -> dict:
        """
        Cover overspending in a category by transferring from another category.
        
        Calculates the negative amount and transfers just enough to bring it to zero.
        
        Args:
            db: Database session
            family_id: Family ID
            overspent_category_id: Category that is overspent (negative available)
            source_category_id: Category to pull money from
            month: Month (YYYY-MM-DD, first day of month)
        
        Returns:
            Dict with transfer details
        """
        # Parse month
        try:
            month_date = datetime.strptime(month, "%Y-%m-%d").date()
            month_date = date(month_date.year, month_date.month, 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid month format. Use YYYY-MM-DD"
            )
        
        # Get overspent category allocation
        overspent_alloc_result = await db.execute(
            select(BudgetAllocation).where(
                and_(
                    BudgetAllocation.category_id == overspent_category_id,
                    BudgetAllocation.month == month_date
                )
            )
        )
        overspent_alloc = overspent_alloc_result.scalar_one_or_none()
        
        if not overspent_alloc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Overspent category allocation not found"
            )
        
        # Calculate how much is needed (transactions - budgeted)
        # TODO: In a full implementation, we'd calculate actual spending from transactions
        # For now, we'll use a simple approach
        
        # If budgeted amount is already positive or zero, nothing to cover
        if overspent_alloc.budgeted_amount >= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category is not overspent"
            )
        
        # Amount needed is the negative of budgeted (to bring to zero)
        amount_needed = abs(overspent_alloc.budgeted_amount)
        
        # Transfer the amount
        return await TransferService.transfer_between_categories(
            db=db,
            family_id=family_id,
            from_category_id=source_category_id,
            to_category_id=overspent_category_id,
            amount=amount_needed,
            month=month,
            notes="Cover overspending",
        )
