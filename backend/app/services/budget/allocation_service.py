"""
Allocation Service

Business logic for budget allocation operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from datetime import date
from uuid import UUID

from app.models.budget import BudgetAllocation
from app.schemas.budget import AllocationCreate, AllocationUpdate
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException


class AllocationService(BaseFamilyService[BudgetAllocation]):
    """Service for budget allocation operations"""

    model = BudgetAllocation

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: AllocationCreate,
    ) -> BudgetAllocation:
        """
        Create a new budget allocation.

        Args:
            db: Database session
            family_id: Family ID
            data: Allocation creation data

        Returns:
            Created allocation

        Raises:
            NotFoundException: If category not found
        """
        # Verify category belongs to family
        from app.services.budget.category_service import CategoryService
        await CategoryService.get_by_id(db, data.category_id, family_id)

        allocation = BudgetAllocation(
            family_id=family_id,
            category_id=data.category_id,
            month=data.month,
            budgeted_amount=data.budgeted_amount,
            notes=data.notes,
        )

        db.add(allocation)
        await db.commit()
        await db.refresh(allocation)
        return allocation

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        allocation_id: UUID,
        family_id: UUID,
        data: AllocationUpdate,
    ) -> BudgetAllocation:
        """
        Update a budget allocation.

        Args:
            db: Database session
            allocation_id: Allocation ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated allocation
        """
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, allocation_id, family_id, update_data)

    @classmethod
    async def get_or_create_for_category_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
        month: date,
    ) -> BudgetAllocation:
        """
        Get existing allocation or create a new one with zero amount.

        Args:
            db: Database session
            family_id: Family ID
            category_id: Category ID
            month: Month (first day)

        Returns:
            Existing or newly created allocation
        """
        # Verify category belongs to family
        from app.services.budget.category_service import CategoryService
        await CategoryService.get_by_id(db, category_id, family_id)

        # Try to find existing allocation
        query = select(BudgetAllocation).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.category_id == category_id,
                BudgetAllocation.month == month,
            )
        )
        result = await db.execute(query)
        allocation = result.scalar_one_or_none()

        if allocation:
            return allocation

        # Create new allocation with zero amount
        allocation = BudgetAllocation(
            family_id=family_id,
            category_id=category_id,
            month=month,
            budgeted_amount=0,
        )
        db.add(allocation)
        await db.commit()
        await db.refresh(allocation)
        return allocation

    @classmethod
    async def list_by_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> List[BudgetAllocation]:
        """
        List all allocations for a given month.

        Args:
            db: Database session
            family_id: Family ID
            month: Month (first day of month)

        Returns:
            List of allocations for the month
        """
        query = (
            select(BudgetAllocation)
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.month == month,
                )
            )
            .order_by(BudgetAllocation.created_at)
        )

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_by_category(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> List[BudgetAllocation]:
        """
        List all allocations for a category across all months.

        Args:
            db: Database session
            category_id: Category ID
            family_id: Family ID for verification

        Returns:
            List of allocations
        """
        # Verify category belongs to family
        from app.services.budget.category_service import CategoryService
        await CategoryService.get_by_id(db, category_id, family_id)

        query = (
            select(BudgetAllocation)
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.category_id == category_id,
                )
            )
            .order_by(BudgetAllocation.month.desc())
        )

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def set_category_budget(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
        month: date,
        amount: int,
    ) -> BudgetAllocation:
        """
        Set budget amount for a category in a specific month.
        Creates allocation if it doesn't exist, updates if it does.

        Args:
            db: Database session
            family_id: Family ID
            category_id: Category ID
            month: Month (first day)
            amount: Budget amount in cents

        Returns:
            Updated or created allocation
        """
        allocation = await cls.get_or_create_for_category_month(
            db, family_id, category_id, month
        )

        allocation.budgeted_amount = amount
        await db.commit()
        await db.refresh(allocation)
        return allocation
