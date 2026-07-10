"""
Allocation Service

Business logic for budget allocation operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.exc import IntegrityError
from typing import List
from datetime import date
from uuid import UUID

from dateutil.relativedelta import relativedelta

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

        # Create new allocation with zero amount. Two concurrent callers can
        # both reach here; the loser hits uq_allocation_category_month, so on
        # IntegrityError roll back and return the row the winner created.
        allocation = BudgetAllocation(
            family_id=family_id,
            category_id=category_id,
            month=month,
            budgeted_amount=0,
        )
        db.add(allocation)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            existing = (await db.execute(query)).scalar_one()
            return existing
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

    @staticmethod
    async def compute_ready_to_assign(
        db: AsyncSession, family_id: UUID, month_date: date
    ) -> int:
        """Envelope 'Ready to Assign' for a month — the single source of truth,
        reused by the month view and the assign-funds endpoint so they never
        diverge. Formula (Actual Budget style):
            on_budget_balance - expense_budgeted_this_month
                              - (prior_expense_budgeted + prior_expense_activity)
        """
        from datetime import timedelta
        from app.services.budget.account_service import AccountService

        if month_date.month == 12:
            end_of_month = date(month_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_of_month = date(month_date.year, month_date.month + 1, 1) - timedelta(days=1)

        total_on_budget = await AccountService.get_total_on_budget_balance(db, family_id, end_of_month)
        this_month = await AllocationService.get_total_expense_budgeted_for_month(db, family_id, month_date)
        prior_budgeted = await AllocationService.get_total_expense_budgeted_before_month(db, family_id, month_date)
        prior_activity = await AllocationService.get_total_expense_activity_before_month(db, family_id, month_date)
        # int() is required: func.sum over BigInteger returns Decimal under
        # asyncpg, which Pydantic serializes as a JSON STRING even on an int
        # field — the frontend's `typeof === 'number'` guard would then silently
        # drop the live Ready-to-Assign update (see CLAUDE.md).
        return int(total_on_budget - this_month - (prior_budgeted + prior_activity))

    @classmethod
    async def set_category_budget(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
        month: date,
        amount: int,
        mode: str = "set",
    ) -> BudgetAllocation:
        """
        Set or add to the budget amount for a category in a specific month.
        Creates the allocation if it doesn't exist.

        Args:
            db: Database session
            family_id: Family ID
            category_id: Category ID
            month: Month (first day)
            amount: Budget amount in cents
            mode: "set" replaces the allocation (default, the API's original
                contract); "add" increments it — the Assign Funds modal
                assigns money ON TOP of what's already budgeted (it used to
                silently replace, wiping the previous allocation).

        Returns:
            Updated or created allocation
        """
        allocation = await cls.get_or_create_for_category_month(
            db, family_id, category_id, month
        )

        if mode == "add":
            allocation.budgeted_amount = (allocation.budgeted_amount or 0) + amount
        else:
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
                        BudgetTransaction.deleted_at.is_(None),
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
    async def get_categories_available_amounts(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
        categories: list,
    ) -> dict:
        """Batched form of get_category_available_amount for many categories.

        Replaces the per-category N+1 (each category ran ~5 queries) with four
        grouped aggregate queries for the whole set. Returns
        ``{str(category_id): summary_dict}`` with the same shape and values as
        get_category_available_amount. Read-only: unlike the single-category path
        it does NOT auto-create allocation rows. Aggregates are cast to int so a
        Decimal sum never serializes as a JSON string to strict mobile clients.
        """
        from datetime import timedelta

        if month.day != 1:
            raise ValueError("month must be the first day of the month")
        if month.month == 12:
            end_of_month = date(month.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_of_month = date(month.year, month.month + 1, 1) - timedelta(days=1)

        cat_ids = [c.id for c in categories]
        if not cat_ids:
            return {}

        async def _grouped(stmt) -> dict:
            return {r[0]: int(r[1] or 0) for r in (await db.execute(stmt)).all()}

        # 1. Budgeted this month, per category.
        budgeted_by_cat = await _grouped(
            select(
                BudgetAllocation.category_id,
                func.coalesce(func.sum(BudgetAllocation.budgeted_amount), 0),
            )
            .where(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.category_id.in_(cat_ids),
                BudgetAllocation.month == month,
            )
            .group_by(BudgetAllocation.category_id)
        )

        # 2. Activity this month, per category (matches get_category_activity:
        #    date in [month, end_of_month], not deleted).
        activity_by_cat = await _grouped(
            select(
                BudgetTransaction.category_id,
                func.coalesce(func.sum(BudgetTransaction.amount), 0),
            )
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.category_id.in_(cat_ids),
                BudgetTransaction.date >= month,
                BudgetTransaction.date <= end_of_month,
                BudgetTransaction.deleted_at.is_(None),
            )
            .group_by(BudgetTransaction.category_id)
        )

        # 3. Prior budgeted (all months before this one), per category.
        prior_budgeted_by_cat = await _grouped(
            select(
                BudgetAllocation.category_id,
                func.coalesce(func.sum(BudgetAllocation.budgeted_amount), 0),
            )
            .where(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.category_id.in_(cat_ids),
                BudgetAllocation.month < month,
            )
            .group_by(BudgetAllocation.category_id)
        )

        # 4. Prior activity (all transactions before this month), per category.
        prior_activity_by_cat = await _grouped(
            select(
                BudgetTransaction.category_id,
                func.coalesce(func.sum(BudgetTransaction.amount), 0),
            )
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.category_id.in_(cat_ids),
                BudgetTransaction.date < month,
                BudgetTransaction.deleted_at.is_(None),
            )
            .group_by(BudgetTransaction.category_id)
        )

        result: dict = {}
        for cat in categories:
            budgeted = budgeted_by_cat.get(cat.id, 0)
            activity = activity_by_cat.get(cat.id, 0)
            previous_balance = 0
            if cat.rollover_enabled:
                previous_balance = (
                    prior_budgeted_by_cat.get(cat.id, 0)
                    + prior_activity_by_cat.get(cat.id, 0)
                )
            result[str(cat.id)] = {
                "category_id": str(cat.id),
                "month": month.isoformat(),
                "budgeted": budgeted,
                "activity": activity,
                "previous_balance": previous_balance,
                "available": previous_balance + budgeted + activity,
                "rollover_enabled": cat.rollover_enabled,
            }
        return result

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
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategoryGroup.deleted_at.is_(None),
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
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategoryGroup.deleted_at.is_(None),
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
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategoryGroup.deleted_at.is_(None),
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
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )

        result = await db.execute(total_query)
        return result.scalar() or 0

    # ------------------------------------------------------------------
    # Auto-fill / budget template methods
    # ------------------------------------------------------------------

    @classmethod
    async def auto_fill(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_month: date,
        strategy: str,
        overwrite_existing: bool = False,
    ) -> dict:
        """Dispatch to the appropriate auto-fill strategy.

        Args:
            db: Database session
            family_id: Family ID
            target_month: First day of the month to fill
            strategy: One of "copy_previous", "average_3", "average_6", "average_12", "from_goals"
            overwrite_existing: If True, overwrite existing allocations; otherwise skip them.

        Returns:
            {"filled_count": int, "skipped_count": int}
        """
        if strategy == "copy_previous":
            return await cls._copy_previous_month(db, family_id, target_month, overwrite_existing)
        elif strategy.startswith("average_"):
            try:
                n = int(strategy.split("_")[1])
            except (IndexError, ValueError):
                raise ValidationError(f"Invalid average strategy: {strategy}")
            return await cls._average_n_months(db, family_id, target_month, n, overwrite_existing)
        elif strategy == "from_goals":
            return await cls._fill_from_goals(db, family_id, target_month, overwrite_existing)
        else:
            raise ValidationError(f"Unknown strategy: {strategy}")

    @classmethod
    async def _copy_previous_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_month: date,
        overwrite_existing: bool,
    ) -> dict:
        """Copy all allocations from the previous month."""
        prev_month = target_month - relativedelta(months=1)
        prev_allocations = await cls.list_by_month(db, family_id, prev_month)

        filled = 0
        skipped = 0
        for alloc in prev_allocations:
            existing = await cls._get_allocation_for_category_month(
                db, family_id, alloc.category_id, target_month
            )
            if existing and not overwrite_existing:
                skipped += 1
                continue

            if existing:
                existing.budgeted_amount = alloc.budgeted_amount
            else:
                new_alloc = BudgetAllocation(
                    family_id=family_id,
                    category_id=alloc.category_id,
                    month=target_month,
                    budgeted_amount=alloc.budgeted_amount,
                )
                db.add(new_alloc)
            filled += 1

        await db.commit()
        return {"filled_count": filled, "skipped_count": skipped}

    @classmethod
    async def _average_n_months(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_month: date,
        n: int,
        overwrite_existing: bool,
    ) -> dict:
        """Set allocations to average of last N months' actual spending per category."""
        from app.services.budget.category_service import CategoryService

        categories = await CategoryService.list_by_family(db, family_id)

        # Date range: N months before target_month
        start_month = target_month - relativedelta(months=n)

        filled = 0
        skipped = 0

        for cat in categories:
            if cat.hidden:
                continue

            # Get actual spending for this category over the N months
            activity_query = (
                select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
                .where(
                    and_(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.category_id == cat.id,
                        BudgetTransaction.date >= start_month,
                        BudgetTransaction.date < target_month,
                        BudgetTransaction.deleted_at.is_(None),
                    )
                )
            )
            activity_result = await db.execute(activity_query)
            total_spent = activity_result.scalar() or 0

            # Average: total_spent is negative for expenses, we want positive budget
            avg_amount = abs(int(total_spent / n)) if n > 0 else 0
            if avg_amount == 0:
                continue

            existing = await cls._get_allocation_for_category_month(
                db, family_id, cat.id, target_month
            )
            if existing and not overwrite_existing:
                skipped += 1
                continue

            if existing:
                existing.budgeted_amount = avg_amount
            else:
                new_alloc = BudgetAllocation(
                    family_id=family_id,
                    category_id=cat.id,
                    month=target_month,
                    budgeted_amount=avg_amount,
                )
                db.add(new_alloc)
            filled += 1

        await db.commit()
        return {"filled_count": filled, "skipped_count": skipped}

    @classmethod
    async def _fill_from_goals(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_month: date,
        overwrite_existing: bool,
    ) -> dict:
        """Set allocations from each category's goal_amount field."""
        from app.services.budget.category_service import CategoryService

        categories = await CategoryService.list_by_family(db, family_id)

        filled = 0
        skipped = 0

        for cat in categories:
            if cat.hidden or cat.goal_amount <= 0:
                continue

            existing = await cls._get_allocation_for_category_month(
                db, family_id, cat.id, target_month
            )
            if existing and not overwrite_existing:
                skipped += 1
                continue

            if existing:
                existing.budgeted_amount = cat.goal_amount
            else:
                new_alloc = BudgetAllocation(
                    family_id=family_id,
                    category_id=cat.id,
                    month=target_month,
                    budgeted_amount=cat.goal_amount,
                )
                db.add(new_alloc)
            filled += 1

        await db.commit()
        return {"filled_count": filled, "skipped_count": skipped}

    @classmethod
    async def _get_allocation_for_category_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
        month: date,
    ) -> BudgetAllocation | None:
        """Get existing allocation for a category/month, or None."""
        query = select(BudgetAllocation).where(
            and_(
                BudgetAllocation.family_id == family_id,
                BudgetAllocation.category_id == category_id,
                BudgetAllocation.month == month,
            )
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Bulk month operations: copy / fill_from_average / carry_over
    # ------------------------------------------------------------------

    @classmethod
    async def copy_from_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        source: date,
        target: date,
        overwrite: bool = False,
    ) -> dict:
        """Copy non-zero allocations from source month to target month.

        Returns {copied, skipped}. With overwrite=False, target allocations
        with non-zero amount are kept unchanged and counted as skipped.
        """
        source_allocs = await cls.list_by_month(db, family_id, source)
        copied = 0
        skipped = 0

        for alloc in source_allocs:
            if alloc.budgeted_amount == 0:
                skipped += 1
                continue

            existing = await cls._get_allocation_for_category_month(
                db, family_id, alloc.category_id, target
            )
            if existing and existing.budgeted_amount != 0 and not overwrite:
                skipped += 1
                continue

            if existing:
                existing.budgeted_amount = alloc.budgeted_amount
            else:
                db.add(BudgetAllocation(
                    family_id=family_id,
                    category_id=alloc.category_id,
                    month=target,
                    budgeted_amount=alloc.budgeted_amount,
                ))
            copied += 1

        await db.commit()
        return {"copied": copied, "skipped": skipped}

    @classmethod
    async def fill_from_average(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target: date,
        months_back: int,
        overwrite: bool = True,
    ) -> dict:
        """Set target month allocations to abs(avg spending) over last N months.

        Excludes income groups and hidden categories. Categories with no
        spending history are skipped. Returns {filled, skipped}.
        """
        if months_back < 1:
            raise ValidationError("months_back must be >= 1")

        start_month = target - relativedelta(months=months_back)

        # Expense categories only (non-income, non-hidden, non-deleted)
        expense_q = (
            select(BudgetCategory)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                    BudgetCategory.hidden == False,
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategoryGroup.deleted_at.is_(None),
                )
            )
        )
        cats = list((await db.execute(expense_q)).scalars().all())

        filled = 0
        skipped = 0

        for cat in cats:
            activity_q = (
                select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
                .where(
                    and_(
                        BudgetTransaction.family_id == family_id,
                        BudgetTransaction.category_id == cat.id,
                        BudgetTransaction.date >= start_month,
                        BudgetTransaction.date < target,
                        BudgetTransaction.deleted_at.is_(None),
                    )
                )
            )
            total = (await db.execute(activity_q)).scalar() or 0
            if total == 0:
                skipped += 1
                continue

            avg = abs(int(total // months_back))
            if avg == 0:
                skipped += 1
                continue

            existing = await cls._get_allocation_for_category_month(
                db, family_id, cat.id, target
            )
            if existing and existing.budgeted_amount != 0 and not overwrite:
                skipped += 1
                continue

            if existing:
                existing.budgeted_amount = avg
            else:
                db.add(BudgetAllocation(
                    family_id=family_id,
                    category_id=cat.id,
                    month=target,
                    budgeted_amount=avg,
                ))
            filled += 1

        await db.commit()
        return {"filled": filled, "skipped": skipped}

    @classmethod
    async def carry_over_month(
        cls,
        db: AsyncSession,
        family_id: UUID,
        source: date,
        target: date,
        mode: str = "all",
    ) -> dict:
        """Carry over remaining balance from source month into target month.

        Modes:
          - "all": carry both positive (unspent) and negative (overspent) balances
          - "unspent_only": skip overspent categories (available < 0)

        New target amount = max(0, target.budgeted + source.available).
        Hidden categories are always skipped. Returns {carried, skipped}.
        """
        if mode not in ("all", "unspent_only"):
            raise ValidationError(f"Invalid mode: {mode}")

        # Expense categories only (non-income, non-hidden, non-deleted)
        expense_q = (
            select(BudgetCategory)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                    BudgetCategory.hidden == False,
                    BudgetCategory.deleted_at.is_(None),
                    BudgetCategoryGroup.deleted_at.is_(None),
                )
            )
        )
        cats = list((await db.execute(expense_q)).scalars().all())

        # Count hidden categories with source allocations as skipped
        hidden_q = (
            select(BudgetCategory)
            .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
            .where(
                and_(
                    BudgetCategory.family_id == family_id,
                    BudgetCategoryGroup.is_income == False,
                    BudgetCategory.hidden == True,
                    BudgetCategory.deleted_at.is_(None),
                )
            )
        )
        hidden_cats = list((await db.execute(hidden_q)).scalars().all())

        carried = 0
        skipped = 0

        for hcat in hidden_cats:
            src = await cls._get_allocation_for_category_month(db, family_id, hcat.id, source)
            if src and src.budgeted_amount != 0:
                skipped += 1

        for cat in cats:
            avail_info = await cls.get_category_available_amount(
                db, family_id, cat.id, source
            )
            available = avail_info["available"]

            if mode == "unspent_only" and available < 0:
                skipped += 1
                continue

            existing = await cls._get_allocation_for_category_month(
                db, family_id, cat.id, target
            )
            current_target = existing.budgeted_amount if existing else 0
            new_amount = max(0, current_target + available)

            if existing:
                existing.budgeted_amount = new_amount
            else:
                db.add(BudgetAllocation(
                    family_id=family_id,
                    category_id=cat.id,
                    month=target,
                    budgeted_amount=new_amount,
                ))
            carried += 1

        await db.commit()
        return {"carried": carried, "skipped": skipped}

    # ------------------------------------------------------------------
    # Cover overspending: move available between categories in one month
    # ------------------------------------------------------------------

    @classmethod
    async def _get_expense_category_or_raise(
        cls,
        db: AsyncSession,
        family_id: UUID,
        category_id: UUID,
    ) -> BudgetCategory:
        """Fetch a non-income, non-deleted category scoped to the family.

        Family scoping lives in the WHERE clause: a category_id belonging to
        another family (or soft-deleted) yields no row → NotFoundException,
        which is what keeps cover-overspending tenant-isolated. Income-group
        categories have no envelope "available" to move, so they're rejected.
        """
        row = (
            await db.execute(
                select(BudgetCategory, BudgetCategoryGroup.is_income)
                .join(BudgetCategoryGroup, BudgetCategory.group_id == BudgetCategoryGroup.id)
                .where(
                    and_(
                        BudgetCategory.id == category_id,
                        BudgetCategory.family_id == family_id,
                        BudgetCategory.deleted_at.is_(None),
                        BudgetCategoryGroup.deleted_at.is_(None),
                    )
                )
            )
        ).first()
        if row is None:
            raise NotFoundException(f"Category {category_id} not found")
        category, is_income = row
        if is_income:
            raise ValidationError(
                "Cover overspending only moves money between expense categories"
            )
        return category

    @classmethod
    async def cover_overspending(
        cls,
        db: AsyncSession,
        family_id: UUID,
        month: date,
        overspent_category_id: UUID,
        source_category_id: UUID,
        amount: int | None = None,
    ) -> dict:
        """Move money from a source category's available into an overspent
        category to cover its deficit, for a single month.

        Mechanics (envelope budgeting): "available" is moved between categories
        by shifting *budgeted* dollars within the SAME month — decrease the
        source's budgeted_amount and increase the target's by the same
        integer-cents amount. Because available = previous_balance + budgeted +
        activity, both envelopes then shift 1:1: the overspent one rises toward
        0 and the source falls. The month's Ready-to-Assign is unchanged (total
        expense budgeted is conserved). The deficit read here already includes
        any negative balance rolled over from prior months, so a carried
        overspend can be covered too.

        Rules (each raises ValidationError, → HTTP 400):
        - source and target must differ
        - both must be expense (non-income) categories in this family
          (a foreign category_id → NotFoundException, → HTTP 404)
        - target must actually be overspent (available < 0); deficit = -available
        - amount defaults to the full deficit; if provided it must satisfy
          0 < amount <= deficit (over-covering is rejected)
        - the source's available must be >= amount — you can't move more money
          than the source envelope holds ("can't over-move")

        Returns the post-move state (available + budgeted) for both categories
        plus the recomputed month-level ready_to_assign.
        """
        month = month.replace(day=1)

        if overspent_category_id == source_category_id:
            raise ValidationError("Source and target categories must be different")

        # Month-lock guard, consistent with create()/update().
        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(db, family_id, month)

        # Family-scoped existence + expense-only checks (NotFound = isolation).
        await cls._get_expense_category_or_raise(db, family_id, overspent_category_id)
        await cls._get_expense_category_or_raise(db, family_id, source_category_id)

        target_info = await cls.get_category_available_amount(
            db, family_id, overspent_category_id, month
        )
        target_available = target_info["available"]
        if target_available >= 0:
            raise ValidationError("Category is not overspent — nothing to cover")
        deficit = -target_available

        if amount is None:
            move = deficit
        else:
            move = int(amount)
            if move <= 0:
                raise ValidationError("Amount to move must be positive")
            if move > deficit:
                raise ValidationError(
                    f"Cannot move more than the overspent amount ({deficit} cents)"
                )

        source_info = await cls.get_category_available_amount(
            db, family_id, source_category_id, month
        )
        source_available = source_info["available"]
        if source_available < move:
            raise ValidationError(
                "Source category does not have enough available "
                f"({source_available} cents) to move {move} cents"
            )

        # Apply the move by shifting budgeted dollars in this month.
        source_alloc = await cls.get_or_create_for_category_month(
            db, family_id, source_category_id, month
        )
        target_alloc = await cls.get_or_create_for_category_month(
            db, family_id, overspent_category_id, month
        )
        source_alloc.budgeted_amount -= move
        target_alloc.budgeted_amount += move
        await db.commit()

        new_source = await cls.get_category_available_amount(
            db, family_id, source_category_id, month
        )
        new_target = await cls.get_category_available_amount(
            db, family_id, overspent_category_id, month
        )
        ready = await cls.compute_ready_to_assign(db, family_id, month)

        return {
            "month": month.isoformat(),
            "amount_moved": move,
            "source": {
                "category_id": str(source_category_id),
                "budgeted": new_source["budgeted"],
                "available": new_source["available"],
            },
            "target": {
                "category_id": str(overspent_category_id),
                "budgeted": new_target["budgeted"],
                "available": new_target["available"],
            },
            "ready_to_assign": ready,
        }
