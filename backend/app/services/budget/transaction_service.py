"""
Transaction Service

Business logic for budget transaction operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional
from datetime import date
from uuid import UUID

from app.models.budget import BudgetTransaction
from app.schemas.budget import TransactionCreate, TransactionUpdate
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationError


class TransactionService(BaseFamilyService[BudgetTransaction]):
    """Service for budget transaction operations"""

    model = BudgetTransaction

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: TransactionCreate,
    ) -> BudgetTransaction:
        """
        Create a new transaction.

        Args:
            db: Database session
            family_id: Family ID
            data: Transaction creation data

        Returns:
            Created transaction

        Raises:
            NotFoundException: If account, category, or payee not found
            ValidationError: If transaction month is closed
        """
        # Check if transaction month is closed
        from app.services.budget.month_locking_service import MonthLockingService
        transaction_month = date(data.date.year, data.date.month, 1)
        await MonthLockingService.validate_month_not_closed(db, family_id, transaction_month)
        
        # Verify account belongs to family
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, data.account_id, family_id)

        # Verify category if provided
        if data.category_id:
            from app.services.budget.category_service import CategoryService
            await CategoryService.get_by_id(db, data.category_id, family_id)

        # Verify payee if provided
        if data.payee_id:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, data.payee_id, family_id)

        # Verify transfer account if provided
        if data.transfer_account_id:
            await AccountService.get_by_id(db, data.transfer_account_id, family_id)

        transaction = BudgetTransaction(
            family_id=family_id,
            account_id=data.account_id,
            date=data.date,
            amount=data.amount,
            payee_id=data.payee_id,
            category_id=data.category_id,
            notes=data.notes,
            cleared=data.cleared,
            reconciled=data.reconciled,
            imported_id=data.imported_id,
            parent_id=data.parent_id,
            is_parent=data.is_parent,
            transfer_account_id=data.transfer_account_id,
        )

        db.add(transaction)
        await db.commit()
        await db.refresh(transaction)
        return transaction

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
        data: TransactionUpdate,
    ) -> BudgetTransaction:
        """
        Update a transaction.

        Args:
            db: Database session
            transaction_id: Transaction ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated transaction
            
        Raises:
            BadRequestException: If transaction month is closed
        """
        # Get the existing transaction to check its date
        existing_txn = await cls.get_by_id(db, transaction_id, family_id)
        transaction_month = date(existing_txn.date.year, existing_txn.date.month, 1)
        
        # Check if transaction month is closed
        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(db, family_id, transaction_month)
        
        update_data = data.model_dump(exclude_unset=True)

        # Verify new account if provided
        if "account_id" in update_data:
            from app.services.budget.account_service import AccountService
            await AccountService.get_by_id(db, update_data["account_id"], family_id)

        # Verify new category if provided
        if "category_id" in update_data and update_data["category_id"]:
            from app.services.budget.category_service import CategoryService
            await CategoryService.get_by_id(db, update_data["category_id"], family_id)

        # Verify new payee if provided
        if "payee_id" in update_data and update_data["payee_id"]:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, update_data["payee_id"], family_id)

        # Verify new transfer account if provided
        if "transfer_account_id" in update_data and update_data["transfer_account_id"]:
            from app.services.budget.account_service import AccountService
            await AccountService.get_by_id(db, update_data["transfer_account_id"], family_id)

        return await cls.update_by_id(db, transaction_id, family_id, update_data)

    @classmethod
    async def list_by_account(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetTransaction]:
        """
        List transactions for an account.

        Args:
            db: Database session
            account_id: Account ID to filter by
            family_id: Family ID for verification
            start_date: Optional start date filter
            end_date: Optional end date filter
            limit: Optional limit
            offset: Optional offset

        Returns:
            List of transactions
        """
        # Verify account belongs to family
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)

        query = (
            select(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                )
            )
            .order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
        )

        if start_date:
            query = query.where(BudgetTransaction.date >= start_date)
        if end_date:
            query = query.where(BudgetTransaction.date <= end_date)
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_by_category(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[BudgetTransaction]:
        """
        List transactions for a category.

        Args:
            db: Database session
            category_id: Category ID to filter by
            family_id: Family ID for verification
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            List of transactions
        """
        # Verify category belongs to family
        from app.services.budget.category_service import CategoryService
        await CategoryService.get_by_id(db, category_id, family_id)

        query = (
            select(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.category_id == category_id,
                )
            )
            .order_by(BudgetTransaction.date.desc())
        )

        if start_date:
            query = query.where(BudgetTransaction.date >= start_date)
        if end_date:
            query = query.where(BudgetTransaction.date <= end_date)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_account_balance(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        as_of_date: Optional[date] = None,
    ) -> int:
        """
        Calculate account balance.

        Args:
            db: Database session
            account_id: Account ID
            family_id: Family ID for verification
            as_of_date: Optional date to calculate balance as of (defaults to all time)

        Returns:
            Balance in cents
        """
        # Verify account belongs to family
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)

        query = (
            select(func.sum(BudgetTransaction.amount))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                )
            )
        )

        if as_of_date:
            query = query.where(BudgetTransaction.date <= as_of_date)

        result = await db.execute(query)
        balance = result.scalar_one_or_none()
        return balance or 0

    @classmethod
    async def get_category_activity(
        cls,
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
        month: date,
    ) -> int:
        """
        Get total spending/income for a category in a month.

        Args:
            db: Database session
            category_id: Category ID
            family_id: Family ID for verification
            month: Month to calculate activity for (should be first day of month)

        Returns:
            Activity amount in cents (sum of transactions)
        """
        # Calculate start and end of month
        from datetime import timedelta
        if month.day != 1:
            raise ValueError("month must be the first day of the month")
        
        # Get last day of month
        if month.month == 12:
            end_of_month = date(month.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_of_month = date(month.year, month.month + 1, 1) - timedelta(days=1)

        query = (
            select(func.sum(BudgetTransaction.amount))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.category_id == category_id,
                    BudgetTransaction.date >= month,
                    BudgetTransaction.date <= end_of_month,
                )
            )
        )

        result = await db.execute(query)
        activity = result.scalar_one_or_none()
        return activity or 0

    @classmethod
    async def reconcile_transaction(
        cls,
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
        reconciled: bool = True,
    ) -> BudgetTransaction:
        """
        Mark a transaction as reconciled or unreconciled.
        
        Args:
            db: Database session
            transaction_id: Transaction ID
            family_id: Family ID for verification
            reconciled: Whether to mark as reconciled
        
        Returns:
            Updated transaction
        """
        transaction = await cls.get_by_id(db, transaction_id, family_id)
        if not transaction:
            raise NotFoundException(f"Transaction {transaction_id} not found")
        
        transaction.reconciled = reconciled
        # Reconciled transactions are automatically marked as cleared
        if reconciled:
            transaction.cleared = True
        
        await db.commit()
        await db.refresh(transaction)
        return transaction
    
    @classmethod
    async def bulk_reconcile_account(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        transaction_ids: List[UUID],
    ) -> int:
        """
        Reconcile multiple transactions for an account.
        
        Args:
            db: Database session
            account_id: Account ID
            family_id: Family ID for verification
            transaction_ids: List of transaction IDs to reconcile
        
        Returns:
            Number of transactions reconciled
        """
        # Verify account belongs to family
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)
        
        # Get all transactions
        query = (
            select(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.id.in_(transaction_ids),
                    BudgetTransaction.account_id == account_id,
                    BudgetTransaction.family_id == family_id,
                )
            )
        )
        result = await db.execute(query)
        transactions = list(result.scalars().all())
        
        # Mark as reconciled
        count = 0
        for transaction in transactions:
            transaction.reconciled = True
            transaction.cleared = True
            count += 1
        
        await db.commit()
        return count
