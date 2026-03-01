"""
Goal Service

Business logic for budget goals and spending targets.
"""

from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID

from app.models.budget import BudgetGoal, BudgetTransaction
from app.schemas.budget import (
    GoalCreate,
    GoalUpdate,
)
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException


class GoalService(BaseFamilyService[BudgetGoal]):
    """Service for budget goal operations"""

    model = BudgetGoal

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: GoalCreate,
    ) -> BudgetGoal:
        """
        Create a new budget goal.

        Args:
            db: Database session
            family_id: Family ID
            data: Goal creation data

        Returns:
            Created budget goal

        Raises:
            NotFoundException: If category not found
        """
        # Verify the category exists and belongs to the family
        from app.services.budget.category_service import CategoryService
        
        await CategoryService.get_by_id(db, data.category_id, family_id)

        goal = BudgetGoal(
            family_id=family_id,
            category_id=data.category_id,
            goal_type=data.goal_type,
            target_amount=data.target_amount,
            period=data.period,
            start_date=data.start_date,
            end_date=data.end_date,
            is_active=data.is_active,
            name=data.name,
            notes=data.notes,
        )

        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        return goal

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        goal_id: UUID,
        family_id: UUID,
        data: GoalUpdate,
    ) -> BudgetGoal:
        """
        Update a budget goal.

        Args:
            db: Database session
            goal_id: Goal ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated budget goal

        Raises:
            NotFoundException: If goal not found or category not found
        """
        # Verify new category if provided
        update_data = data.model_dump(exclude_unset=True)
        if "category_id" in update_data:
            from app.services.budget.category_service import CategoryService
            
            await CategoryService.get_by_id(db, update_data["category_id"], family_id)

        return await cls.update_by_id(db, goal_id, family_id, update_data)

    @classmethod
    async def list_by_category(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
        active_only: bool = True,
    ) -> List[BudgetGoal]:
        """
        List all goals for a specific category.

        Args:
            db: Database session
            category_id: Category ID to filter by
            family_id: Family ID for verification
            active_only: Whether to only return active goals

        Returns:
            List of budget goals

        Raises:
            NotFoundException: If category not found
        """
        # Verify category exists
        from app.services.budget.category_service import CategoryService
        
        await CategoryService.get_by_id(db, category_id, family_id)

        query = (
            select(BudgetGoal)
            .where(
                and_(
                    BudgetGoal.family_id == family_id,
                    BudgetGoal.category_id == category_id,
                )
            )
            .order_by(BudgetGoal.created_at.desc())
        )

        if active_only:
            query = query.where(BudgetGoal.is_active == True)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_active(
        cls,
        db: AsyncSession,
        family_id: UUID,
        target_date: Optional[date] = None,
    ) -> List[BudgetGoal]:
        """
        List all active goals for a family.

        Args:
            db: Database session
            family_id: Family ID
            target_date: Optional date to check goal validity (defaults to today)

        Returns:
            List of active budget goals that are valid on the target date
        """
        if target_date is None:
            target_date = date.today()

        query = (
            select(BudgetGoal)
            .where(
                and_(
                    BudgetGoal.family_id == family_id,
                    BudgetGoal.is_active == True,
                    BudgetGoal.start_date <= target_date,
                )
            )
            .order_by(BudgetGoal.created_at.desc())
        )

        # Filter by end_date if specified (null end_date means ongoing)
        # Include goals where end_date is null OR end_date >= target_date
        from sqlalchemy import or_
        
        query = query.where(
            or_(
                BudgetGoal.end_date.is_(None),
                BudgetGoal.end_date >= target_date,
            )
        )

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def calculate_progress(
        cls,
        db: AsyncSession,
        goal_id: UUID,
        family_id: UUID,
    ) -> dict:
        """
        Calculate progress towards a goal.

        Args:
            db: Database session
            goal_id: Goal ID
            family_id: Family ID for verification

        Returns:
            Dictionary with:
                - goal_id: UUID
                - goal_name: str
                - goal_type: str ('spending_limit' or 'savings_target')
                - target_amount: int (in cents)
                - actual_amount: int (in cents, absolute value)
                - period: str
                - start_date: date
                - end_date: Optional[date]
                - on_track: bool (True if goal is being met)
                - percentage: float (0-100)

        Raises:
            NotFoundException: If goal not found
        """
        goal = await cls.get_by_id(db, goal_id, family_id)

        # Calculate actual spending/income for the goal period
        actual_amount = await cls._calculate_period_amount(
            db, goal.category_id, goal.goal_type, goal.period, goal.start_date
        )

        # Determine if goal is on track
        if goal.goal_type == "spending_limit":
            # For spending limits, actual should be <= target
            on_track = actual_amount <= goal.target_amount
            percentage = (actual_amount / goal.target_amount * 100) if goal.target_amount > 0 else 0
        else:  # savings_target
            # For savings targets, actual should be >= target
            on_track = actual_amount >= goal.target_amount
            percentage = (actual_amount / goal.target_amount * 100) if goal.target_amount > 0 else 0

        return {
            "goal_id": goal.id,
            "goal_name": goal.name,
            "goal_type": goal.goal_type,
            "target_amount": goal.target_amount,
            "actual_amount": actual_amount,
            "period": goal.period,
            "start_date": goal.start_date,
            "end_date": goal.end_date,
            "on_track": on_track,
            "percentage": min(100, percentage),  # Cap at 100%
        }

    @classmethod
    async def _calculate_period_amount(
        cls,
        db: AsyncSession,
        category_id: UUID,
        goal_type: str,
        period: str,
        start_date: date,
    ) -> int:
        """
        Calculate the sum of transactions for a goal period.

        Args:
            db: Database session
            category_id: Category ID
            goal_type: Type of goal ('spending_limit' or 'savings_target')
            period: Period type ('monthly', 'quarterly', 'annual')
            start_date: Start date of the period

        Returns:
            Sum of transaction amounts in cents (absolute value)
        """
        from datetime import timedelta
        from sqlalchemy import func

        # Calculate end date based on period
        if period == "monthly":
            if start_date.month == 12:
                end_date = date(start_date.year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(start_date.year, start_date.month + 1, 1) - timedelta(days=1)
        elif period == "quarterly":
            quarter_month = ((start_date.month - 1) // 3) * 3 + 3
            if quarter_month > 12:
                end_date = date(start_date.year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(start_date.year, quarter_month + 1, 1) - timedelta(days=1)
        else:  # annual
            end_date = date(start_date.year, 12, 31)

        # Query transactions for the period
        query = (
            select(func.sum(func.abs(BudgetTransaction.amount)))
            .where(
                and_(
                    BudgetTransaction.category_id == category_id,
                    BudgetTransaction.transaction_date >= start_date,
                    BudgetTransaction.transaction_date <= end_date,
                    BudgetTransaction.amount < 0,  # Only expenses for spending_limit, income for savings_target
                )
                if goal_type == "spending_limit"
                else and_(
                    BudgetTransaction.category_id == category_id,
                    BudgetTransaction.transaction_date >= start_date,
                    BudgetTransaction.transaction_date <= end_date,
                    BudgetTransaction.amount > 0,  # Income only for savings targets
                )
            )
        )

        result = await db.execute(query)
        total = result.scalar_one()

        return int(total) if total else 0
