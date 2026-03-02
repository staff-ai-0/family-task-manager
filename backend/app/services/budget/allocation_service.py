"""
Allocation Service

Business logic for budget allocation operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List
from datetime import date
from uuid import UUID

from app.models.budget import BudgetAllocation, BudgetTransaction, BudgetCategory, BudgetCategoryGroup
from app.schemas.budget import AllocationCreate, AllocationUpdate
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationError


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
            ValidationError: If month is closed
        """
        # Check if month is closed
        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(db, family_id, data.month)
        
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
            
        Raises:
            ValidationError: If month is closed
        """
        # Get existing allocation to check month
        existing_allocation = await cls.get_by_id(db, allocation_id, family_id)
        
        # Check if month is closed
        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(db, family_id, existing_allocation.month)
        
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

    @classmethod
    async def get_category_available_amount(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
        month: date,
    ) -> dict:
        """
        Calculate available amount for a category in a given month.
        
        Formula: Available = Previous Balance + Budgeted + Activity
        
        Where:
        - Previous Balance = rollover from previous month (if enabled)
        - Budgeted = amount allocated this month
        - Activity = sum of transactions in this month (negative for expenses)
        
        Args:
            db: Database session
            family_id: Family ID
            category_id: Category ID
            month: Month to calculate for
        
        Returns:
            Dict with budgeted, activity, previous_balance, and available amounts
        """
        from app.services.budget.category_service import CategoryService
        from app.services.budget.transaction_service import TransactionService
        
        # Get category to check rollover setting
        category = await CategoryService.get_by_id(db, category_id, family_id)
        if not category:
            raise NotFoundException(f"Category {category_id} not found")
        
        # Get current month's allocation
        allocation = await cls.get_or_create_for_category_month(
            db, family_id, category_id, month
        )
        budgeted = allocation.budgeted_amount
        
        # Calculate activity (transactions) for this month
        activity = await TransactionService.get_category_activity(
            db, category_id, family_id, month
        )
        
        previous_balance = 0
        if category.rollover_enabled:
            prev_alloc_query = (
                select(func.coalesce(func.sum(BudgetAllocation.budgeted_amount), 0))
                .where(
                    and_(
                        BudgetAllocation.family_id == family_id,
                        BudgetAllocation.category_id == category_id,
                        BudgetAllocation.month < month,
                    )
                )
            )
            prev_alloc_result = await db.execute(prev_alloc_query)
            prev_budgeted = prev_alloc_result.scalar() or 0

            prev_activity_query = (
                select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
                .where(
                    and_(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.category_id == category_id,
                        BudgetTransaction.date < month,
                    )
                )
            )
            prev_activity_result = await db.execute(prev_activity_query)
            prev_activity = prev_activity_result.scalar() or 0

            previous_balance = prev_budgeted + prev_activity
        
        available = previous_balance + budgeted + activity

        return {
            "category_id": str(category_id),
            "month": month.isoformat(),
            "budgeted": budgeted,
            "activity": activity,
            "previous_balance": previous_balance,
            "available": available,
            "rollover_enabled": category.rollover_enabled,
        }
    
    @classmethod
    async def get_month_summary(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> dict:
        """
        Get complete budget summary for a month with all categories.
        
        Returns budgeted, activity, and available amounts for each category.
        
        Args:
            db: Database session
            family_id: Family ID
            month: Month to summarize
        
        Returns:
            Dict with category summaries and totals
        """
        from app.services.budget.category_service import CategoryService
        
        # Get all categories
        categories = await CategoryService.list_by_family(db, family_id)
        
        category_summaries = []
        total_budgeted = 0
        total_activity = 0
        total_available = 0
        
        for category in categories:
            if category.hidden:
                continue
            
            summary = await cls.get_category_available_amount(
                db, family_id, category.id, month
            )
            
            category_summaries.append({
                **summary,
                "category_name": category.name,
                "group_id": str(category.group_id),
            })
            
            total_budgeted += summary["budgeted"]
            total_activity += summary["activity"]
            total_available += summary["available"]
        
        return {
            "month": month.isoformat(),
            "categories": category_summaries,
            "totals": {
                "budgeted": total_budgeted,
                "activity": total_activity,
                "available": total_available,
            },
        }

    @classmethod
    async def get_total_expense_budgeted_for_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> int:
        """
        Get total budgeted amount for all EXPENSE categories in a given month.

        Income category groups (is_income=True) are excluded — their allocations
        don't reduce the "Ready to Assign" pool.

        Args:
            db: Database session
            family_id: Family ID
            month: The month (first day)

        Returns:
            Total budgeted amount in cents for expense categories this month
        """
        # Sub-query: IDs of all expense (non-income) categories for this family
        expense_category_ids_query = (
            select(BudgetCategory.id)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                )
            )
        )

        total_query = (
            select(func.coalesce(func.sum(BudgetAllocation.budgeted_amount), 0))
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.month == month,
                    BudgetAllocation.category_id.in_(expense_category_ids_query),
                )
            )
        )

        result = await db.execute(total_query)
        return result.scalar() or 0

    @classmethod
    async def get_total_expense_budgeted_before_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> int:
        """
        Get total budgeted amount for all EXPENSE categories in ALL months BEFORE the given month.

        This is used to calculate how much of the total account balance has already been
        "spoken for" by previous months' budgets that weren't fully spent (i.e., rolled over).

        Args:
            db: Database session
            family_id: Family ID
            month: The reference month (first day); only prior months are counted

        Returns:
            Total budgeted amount in cents for expense categories before this month
        """
        expense_category_ids_query = (
            select(BudgetCategory.id)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                )
            )
        )

        total_query = (
            select(func.coalesce(func.sum(BudgetAllocation.budgeted_amount), 0))
            .where(
                and_(
                    BudgetAllocation.family_id == family_id,
                    BudgetAllocation.month < month,
                    BudgetAllocation.category_id.in_(expense_category_ids_query),
                )
            )
        )

        result = await db.execute(total_query)
        return result.scalar() or 0

    @classmethod
    async def get_total_expense_activity_before_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
    ) -> int:
        """
        Get total transaction activity for all EXPENSE categories in ALL months BEFORE the given month.

        Combined with get_total_expense_budgeted_before_month, this lets us compute the
        net carried-forward balance from prior months:
          prior_net = prior_budgeted + prior_activity  (activity is negative for expenses)

        Args:
            db: Database session
            family_id: Family ID
            month: Reference month (first day); only prior months are counted

        Returns:
            Total activity amount in cents (negative = spending)
        """
        from datetime import timedelta

        # Last day of the month prior to `month`
        end_of_prior = month - timedelta(days=1)

        expense_category_ids_query = (
            select(BudgetCategory.id)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                )
            )
        )

        total_query = (
            select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.category_id.in_(expense_category_ids_query),
                    BudgetTransaction.date <= end_of_prior,
                )
            )
        )

        result = await db.execute(total_query)
        return result.scalar() or 0
