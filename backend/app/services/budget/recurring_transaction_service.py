"""
Recurring Transaction Service

Business logic for recurring/scheduled transaction templates.
"""

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional
from uuid import UUID

from app.models.budget import BudgetRecurringTransaction, BudgetTransaction
from app.schemas.budget import (
    RecurringTransactionCreate,
    RecurringTransactionUpdate,
)
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException


class RecurringTransactionService(BaseFamilyService[BudgetRecurringTransaction]):
    """Service for recurring transaction operations"""

    model = BudgetRecurringTransaction

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: RecurringTransactionCreate,
    ) -> BudgetRecurringTransaction:
        """
        Create a new recurring transaction template.

        Args:
            db: Database session
            family_id: Family ID
            data: Recurring transaction creation data

        Returns:
            Created recurring transaction

        Raises:
            NotFoundException: If account not found
        """
        # Verify the account exists and belongs to the family
        from app.services.budget.account_service import AccountService
        
        await AccountService.get_by_id(db, data.account_id, family_id)

        # Verify category if provided
        if data.category_id:
            from app.services.budget.category_service import CategoryService
            
            await CategoryService.get_by_id(db, data.category_id, family_id)

        # Calculate next due date
        next_due_date = cls._calculate_next_occurrence(
            data.start_date,
            data.recurrence_type,
            data.recurrence_interval,
            data.recurrence_pattern,
            data.end_date,
        )

        recurring_tx = BudgetRecurringTransaction(
            family_id=family_id,
            account_id=data.account_id,
            category_id=data.category_id,
            payee_id=data.payee_id,
            name=data.name,
            description=data.description,
            amount=data.amount,
            recurrence_type=data.recurrence_type,
            recurrence_interval=data.recurrence_interval,
            recurrence_pattern=data.recurrence_pattern,
            start_date=data.start_date,
            end_date=data.end_date,
            is_active=data.is_active,
            next_due_date=next_due_date,
        )

        db.add(recurring_tx)
        await db.commit()
        await db.refresh(recurring_tx)
        return recurring_tx

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        recurring_id: UUID,
        family_id: UUID,
        data: RecurringTransactionUpdate,
    ) -> BudgetRecurringTransaction:
        """
        Update a recurring transaction template.

        Args:
            db: Database session
            recurring_id: Recurring transaction ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated recurring transaction

        Raises:
            NotFoundException: If recurring transaction not found or account not found
        """
        # Verify new account if provided
        update_data = data.model_dump(exclude_unset=True)
        if "account_id" in update_data:
            from app.services.budget.account_service import AccountService
            
            await AccountService.get_by_id(db, update_data["account_id"], family_id)

        # Verify new category if provided
        if "category_id" in update_data and update_data["category_id"]:
            from app.services.budget.category_service import CategoryService
            
            await CategoryService.get_by_id(db, update_data["category_id"], family_id)

        # Recalculate next_due_date if any recurrence fields changed
        recurring = await cls.get_by_id(db, recurring_id, family_id)
        
        start_date = update_data.get("start_date", recurring.start_date)
        recurrence_type = update_data.get("recurrence_type", recurring.recurrence_type)
        recurrence_interval = update_data.get("recurrence_interval", recurring.recurrence_interval)
        recurrence_pattern = update_data.get("recurrence_pattern", recurring.recurrence_pattern)
        end_date = update_data.get("end_date", recurring.end_date)
        
        if any(k in update_data for k in ["start_date", "recurrence_type", "recurrence_interval", "recurrence_pattern", "end_date"]):
            next_due_date = cls._calculate_next_occurrence(
                start_date, recurrence_type, recurrence_interval, recurrence_pattern, end_date
            )
            update_data["next_due_date"] = next_due_date

        return await cls.update_by_id(db, recurring_id, family_id, update_data)

    @classmethod
    async def list_by_account(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        active_only: bool = True,
    ) -> List[BudgetRecurringTransaction]:
        """
        List all recurring transactions for a specific account.

        Args:
            db: Database session
            account_id: Account ID to filter by
            family_id: Family ID for verification
            active_only: Whether to only return active templates

        Returns:
            List of recurring transactions
        """
        query = (
            select(BudgetRecurringTransaction)
            .where(
                and_(
                    BudgetRecurringTransaction.family_id == family_id,
                    BudgetRecurringTransaction.account_id == account_id,
                )
            )
            .order_by(BudgetRecurringTransaction.created_at.desc())
        )

        if active_only:
            query = query.where(BudgetRecurringTransaction.is_active == True)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_due_for_posting(
        cls,
        db: AsyncSession,
        family_id: UUID,
        as_of_date: Optional[date] = None,
    ) -> List[BudgetRecurringTransaction]:
        """
        List recurring transactions that are due for posting.

        Args:
            db: Database session
            family_id: Family ID
            as_of_date: Check due date as of this date (defaults to today)

        Returns:
            List of recurring transactions due for posting
        """
        if as_of_date is None:
            as_of_date = date.today()

        query = (
            select(BudgetRecurringTransaction)
            .where(
                and_(
                    BudgetRecurringTransaction.family_id == family_id,
                    BudgetRecurringTransaction.is_active == True,
                    BudgetRecurringTransaction.next_due_date <= as_of_date,
                )
            )
            .order_by(BudgetRecurringTransaction.next_due_date.asc())
        )

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    def _calculate_next_occurrence(
        cls,
        start_date: date,
        recurrence_type: str,
        recurrence_interval: int,
        recurrence_pattern: Optional[dict],
        end_date: Optional[date],
        from_date: Optional[date] = None,
    ) -> Optional[date]:
        """
        Calculate the next occurrence date for a recurring transaction.

        Args:
            start_date: Template start date
            recurrence_type: Type of recurrence
            recurrence_interval: Frequency (every N periods)
            recurrence_pattern: Pattern-specific config
            end_date: Template end date (None = ongoing)
            from_date: Calculate next date from this date (defaults to today)

        Returns:
            Next occurrence date or None if template has expired
        """
        if from_date is None:
            from_date = date.today()

        # If start date is in future, return start date
        if start_date > from_date:
            return start_date

        # Check if already expired
        if end_date and from_date > end_date:
            return None

        next_date = None

        if recurrence_type == "daily":
            # Calculate next occurrence: from_date + (interval days)
            days_since_start = (from_date - start_date).days
            intervals_passed = days_since_start // recurrence_interval
            next_date = start_date + timedelta(days=(intervals_passed + 1) * recurrence_interval)

        elif recurrence_type == "weekly":
            # recurrence_pattern contains list of day numbers (0=Mon, 6=Sun)
            if not recurrence_pattern or "days" not in recurrence_pattern:
                # Default to same day of week as start_date
                target_days = [start_date.weekday()]
            else:
                target_days = recurrence_pattern["days"]

            weeks_since_start = (from_date - start_date).days // 7
            
            # Find next occurrence on target days
            current_check = from_date
            for _ in range(14):  # Check up to 2 weeks ahead
                if current_check.weekday() in target_days and current_check >= start_date:
                    # Check if it's the right interval
                    weeks_diff = (current_check - start_date).days // 7
                    if weeks_diff % recurrence_interval == 0 and current_check > from_date:
                        next_date = current_check
                        break
                current_check += timedelta(days=1)

        elif recurrence_type == "monthly_dayofmonth":
            # recurrence_pattern contains target day of month (1-31)
            if not recurrence_pattern or "day" not in recurrence_pattern:
                target_day = start_date.day
            else:
                target_day = recurrence_pattern["day"]

            # Find next occurrence
            current_date = from_date.replace(day=1)
            months_offset = 0
            while months_offset < 24:  # Check up to 2 years
                target_date = (current_date + relativedelta(months=months_offset)).replace(day=1)
                
                # Handle months with fewer days
                try:
                    target_date = target_date.replace(day=target_day)
                except ValueError:
                    # Month doesn't have that day (e.g., 31st of Feb), use last day
                    target_date = (target_date + relativedelta(months=1)) - timedelta(days=1)

                if target_date > from_date:
                    months_diff = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
                    if months_diff % recurrence_interval == 0:
                        next_date = target_date
                        break

                months_offset += recurrence_interval

        elif recurrence_type == "monthly_dayofweek":
            # recurrence_pattern: {"week": 0-4 or -1 for last, "day": 0-6}
            if not recurrence_pattern or "week" not in recurrence_pattern or "day" not in recurrence_pattern:
                # Default to same week/day as start_date
                pattern_week = (start_date.day - 1) // 7
                pattern_day = start_date.weekday()
            else:
                pattern_week = recurrence_pattern["week"]
                pattern_day = recurrence_pattern["day"]

            months_offset = 0
            while months_offset < 24:
                check_date = from_date + relativedelta(months=months_offset)
                check_date = check_date.replace(day=1)  # Start at first of month

                # Find target day in target week
                current_day = check_date.weekday()
                days_until_target = (pattern_day - current_day) % 7
                target_date = check_date + timedelta(days=days_until_target)

                # Adjust for week number
                if pattern_week == -1:
                    # Last occurrence: go forward a month and back
                    target_date = (target_date + relativedelta(months=1)).replace(day=1) - timedelta(days=1)
                    # Find the target day on or before this date
                    while target_date.weekday() != pattern_day:
                        target_date -= timedelta(days=1)
                else:
                    # Specific week
                    target_date += timedelta(weeks=pattern_week)

                if target_date > from_date:
                    months_diff = (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)
                    if months_diff % recurrence_interval == 0:
                        next_date = target_date
                        break

                months_offset += recurrence_interval

        # Verify within end date
        if next_date and end_date and next_date > end_date:
            return None

        return next_date

    @classmethod
    async def post_transaction(
        cls,
        db: AsyncSession,
        recurring_id: UUID,
        family_id: UUID,
        transaction_date: Optional[date] = None,
    ) -> BudgetTransaction:
        """
        Post a transaction from a recurring template.

        Args:
            db: Database session
            recurring_id: Recurring transaction template ID
            family_id: Family ID for verification
            transaction_date: Date to post transaction (defaults to today)

        Returns:
            Created transaction

        Raises:
            NotFoundException: If recurring transaction not found
        """
        if transaction_date is None:
            transaction_date = date.today()

        recurring = await cls.get_by_id(db, recurring_id, family_id)

        # Create transaction from template
        transaction = BudgetTransaction(
            family_id=family_id,
            account_id=recurring.account_id,
            category_id=recurring.category_id,
            payee_id=recurring.payee_id,
            amount=recurring.amount,
            transaction_date=transaction_date,
            description=recurring.description or recurring.name,
            cleared=False,
            reconciled=False,
        )

        db.add(transaction)

        # Update recurring transaction's last_generated_date and next_due_date
        recurring.last_generated_date = transaction_date
        recurring.next_due_date = cls._calculate_next_occurrence(
            recurring.start_date,
            recurring.recurrence_type,
            recurring.recurrence_interval,
            recurring.recurrence_pattern,
            recurring.end_date,
            from_date=transaction_date,
        )

        await db.commit()
        await db.refresh(transaction)
        return transaction
