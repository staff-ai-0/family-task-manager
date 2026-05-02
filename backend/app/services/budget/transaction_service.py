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
from app.schemas.budget import TransactionCreate, TransactionUpdate, SplitChild
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

        # Resolve payee: verify existing or auto-create from payee_name
        resolved_payee_id = data.payee_id
        payee_name = getattr(data, "payee_name", None)
        if resolved_payee_id:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, resolved_payee_id, family_id)
        elif payee_name:
            from app.services.budget.payee_service import PayeeService
            payee = await PayeeService.get_or_create_by_name(db, family_id, payee_name)
            resolved_payee_id = payee.id

        # Verify transfer account if provided
        if data.transfer_account_id:
            await AccountService.get_by_id(db, data.transfer_account_id, family_id)

        transaction = BudgetTransaction(
            family_id=family_id,
            account_id=data.account_id,
            date=data.date,
            amount=data.amount,
            payee_id=resolved_payee_id,
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
        payee_name = update_data.pop("payee_name", None)

        # Verify new account if provided
        if "account_id" in update_data:
            from app.services.budget.account_service import AccountService
            await AccountService.get_by_id(db, update_data["account_id"], family_id)

        # Verify new category if provided
        if "category_id" in update_data and update_data["category_id"]:
            from app.services.budget.category_service import CategoryService
            await CategoryService.get_by_id(db, update_data["category_id"], family_id)

        # Resolve payee: verify existing or auto-create from payee_name
        if "payee_id" in update_data and update_data["payee_id"]:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, update_data["payee_id"], family_id)
        elif payee_name and "payee_id" not in update_data:
            from app.services.budget.payee_service import PayeeService
            payee = await PayeeService.get_or_create_by_name(db, family_id, payee_name)
            update_data["payee_id"] = payee.id

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
                    BudgetTransaction.deleted_at.is_(None),
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
                    BudgetTransaction.deleted_at.is_(None),
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
                    BudgetTransaction.deleted_at.is_(None),
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
                    BudgetTransaction.deleted_at.is_(None),
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
                    BudgetTransaction.deleted_at.is_(None),
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

    # ------------------------------------------------------------------
    # Split transactions
    # ------------------------------------------------------------------

    @classmethod
    async def create_split(
        cls,
        db: AsyncSession,
        family_id: UUID,
        *,
        account_id: UUID,
        txn_date: date,
        splits: List[SplitChild],
        payee_id: Optional[UUID] = None,
        payee_name: Optional[str] = None,
        notes: Optional[str] = None,
        cleared: bool = False,
        reconciled: bool = False,
    ) -> BudgetTransaction:
        """Create a parent split transaction with N child legs.

        Parent has aggregate amount, no category. Children share account/date/payee
        but each has its own category and amount. Sum of children == parent.amount.
        """
        if len(splits) < 2:
            raise ValidationError("Split requires at least 2 child legs")

        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(
            db, family_id, date(txn_date.year, txn_date.month, 1)
        )

        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)

        resolved_payee_id = payee_id
        if payee_id:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, payee_id, family_id)
        elif payee_name:
            from app.services.budget.payee_service import PayeeService
            payee = await PayeeService.get_or_create_by_name(db, family_id, payee_name)
            resolved_payee_id = payee.id

        from app.services.budget.category_service import CategoryService
        for s in splits:
            if s.category_id:
                await CategoryService.get_by_id(db, s.category_id, family_id)
            if s.payee_id:
                from app.services.budget.payee_service import PayeeService
                await PayeeService.get_by_id(db, s.payee_id, family_id)

        total = sum(s.amount for s in splits)

        parent = BudgetTransaction(
            family_id=family_id,
            account_id=account_id,
            date=txn_date,
            amount=total,
            payee_id=resolved_payee_id,
            category_id=None,
            notes=notes,
            cleared=cleared,
            reconciled=reconciled,
            is_parent=True,
        )
        db.add(parent)
        await db.flush()

        for s in splits:
            child = BudgetTransaction(
                family_id=family_id,
                account_id=account_id,
                date=txn_date,
                amount=s.amount,
                payee_id=s.payee_id or resolved_payee_id,
                category_id=s.category_id,
                notes=s.notes,
                cleared=cleared,
                reconciled=reconciled,
                parent_id=parent.id,
                is_parent=False,
            )
            db.add(child)

        await db.commit()
        await db.refresh(parent)
        return parent

    @classmethod
    async def get_split_children(
        cls,
        db: AsyncSession,
        parent_id: UUID,
        family_id: UUID,
    ) -> List[BudgetTransaction]:
        """Return child legs of a split parent."""
        parent = await cls.get_by_id(db, parent_id, family_id)
        if not parent.is_parent:
            raise ValidationError("Transaction is not a split parent")
        query = (
            select(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.parent_id == parent_id,
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .order_by(BudgetTransaction.created_at.asc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def replace_split_children(
        cls,
        db: AsyncSession,
        parent_id: UUID,
        family_id: UUID,
        splits: List[SplitChild],
    ) -> BudgetTransaction:
        """Replace child legs of a split parent. Updates parent total."""
        if len(splits) < 2:
            raise ValidationError("Split requires at least 2 child legs")

        parent = await cls.get_by_id(db, parent_id, family_id)
        if not parent.is_parent:
            raise ValidationError("Transaction is not a split parent")

        from app.services.budget.month_locking_service import MonthLockingService
        await MonthLockingService.validate_month_not_closed(
            db, family_id, date(parent.date.year, parent.date.month, 1)
        )

        from app.services.budget.category_service import CategoryService
        from app.services.budget.payee_service import PayeeService
        for s in splits:
            if s.category_id:
                await CategoryService.get_by_id(db, s.category_id, family_id)
            if s.payee_id:
                await PayeeService.get_by_id(db, s.payee_id, family_id)

        # Hard-delete existing children (cascade was set in model relationship)
        existing = await cls.get_split_children(db, parent_id, family_id)
        for child in existing:
            await db.delete(child)
        await db.flush()

        total = sum(s.amount for s in splits)
        parent.amount = total

        for s in splits:
            child = BudgetTransaction(
                family_id=family_id,
                account_id=parent.account_id,
                date=parent.date,
                amount=s.amount,
                payee_id=s.payee_id or parent.payee_id,
                category_id=s.category_id,
                notes=s.notes,
                cleared=parent.cleared,
                reconciled=parent.reconciled,
                parent_id=parent.id,
                is_parent=False,
            )
            db.add(child)

        await db.commit()
        await db.refresh(parent)
        return parent

    # ------------------------------------------------------------------
    # Search & bulk operations
    # ------------------------------------------------------------------

    @classmethod
    async def search_transactions(
        cls,
        db: AsyncSession,
        family_id: UUID,
        *,
        account_id: Optional[UUID] = None,
        category_id: Optional[UUID] = None,
        payee_id: Optional[UUID] = None,
        cleared: Optional[bool] = None,
        reconciled: Optional[bool] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        amount_min: Optional[int] = None,
        amount_max: Optional[int] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetTransaction]:
        """Filter transactions by any combination of criteria."""
        query = select(BudgetTransaction).where(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_(None),
        )
        if account_id is not None:
            query = query.where(BudgetTransaction.account_id == account_id)
        if category_id is not None:
            query = query.where(BudgetTransaction.category_id == category_id)
        if payee_id is not None:
            query = query.where(BudgetTransaction.payee_id == payee_id)
        if cleared is not None:
            query = query.where(BudgetTransaction.cleared == cleared)
        if reconciled is not None:
            query = query.where(BudgetTransaction.reconciled == reconciled)
        if start_date is not None:
            query = query.where(BudgetTransaction.date >= start_date)
        if end_date is not None:
            query = query.where(BudgetTransaction.date <= end_date)
        if amount_min is not None:
            query = query.where(BudgetTransaction.amount >= amount_min)
        if amount_max is not None:
            query = query.where(BudgetTransaction.amount <= amount_max)
        if search:
            query = query.where(BudgetTransaction.notes.ilike(f"%{search}%"))

        query = query.order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    BULK_UPDATE_ALLOWED = frozenset({"cleared", "reconciled", "category_id", "payee_id"})

    @classmethod
    async def bulk_update_transactions(
        cls,
        db: AsyncSession,
        family_id: UUID,
        transaction_ids: List[UUID],
        updates: dict,
    ) -> int:
        """Apply same field updates to N transactions. Returns count modified.

        Whitelist: cleared, reconciled, category_id, payee_id. Other fields dropped.
        """
        if not transaction_ids:
            return 0
        filtered = {k: v for k, v in updates.items() if k in cls.BULK_UPDATE_ALLOWED}
        if not filtered:
            return 0

        # Coerce string UUIDs and verify FK targets belong to this family.
        for field in ("category_id", "payee_id"):
            if field in filtered and filtered[field] is not None:
                value = filtered[field]
                if isinstance(value, str):
                    value = UUID(value)
                    filtered[field] = value
                if field == "category_id":
                    from app.services.budget.category_service import CategoryService
                    await CategoryService.get_by_id(db, value, family_id)
                else:
                    from app.services.budget.payee_service import PayeeService
                    await PayeeService.get_by_id(db, value, family_id)

        query = select(BudgetTransaction).where(
            and_(
                BudgetTransaction.id.in_(transaction_ids),
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
        result = await db.execute(query)
        rows = list(result.scalars().all())

        for txn in rows:
            for field, value in filtered.items():
                setattr(txn, field, value)

        await db.commit()
        return len(rows)

    @classmethod
    async def bulk_delete_transactions(
        cls,
        db: AsyncSession,
        family_id: UUID,
        transaction_ids: List[UUID],
    ) -> int:
        """Delete N transactions (family-scoped). Returns count deleted."""
        if not transaction_ids:
            return 0

        query = select(BudgetTransaction).where(
            and_(
                BudgetTransaction.id.in_(transaction_ids),
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
        result = await db.execute(query)
        rows = list(result.scalars().all())

        for txn in rows:
            await db.delete(txn)
        await db.commit()
        return len(rows)

    @classmethod
    async def finish_reconciliation(
        cls,
        db: AsyncSession,
        family_id: UUID,
        *,
        account_id: UUID,
        statement_balance: int,
        transaction_ids: List[UUID],
    ) -> dict:
        """Mark transactions cleared+reconciled, create adjustment if balance mismatches.

        Returns {reconciled_count, adjustment_amount, adjustment_transaction_id}.
        """
        from app.services.budget.account_service import AccountService
        await AccountService.get_by_id(db, account_id, family_id)

        query = select(BudgetTransaction).where(
            and_(
                BudgetTransaction.id.in_(transaction_ids),
                BudgetTransaction.account_id == account_id,
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
        result = await db.execute(query)
        rows = list(result.scalars().all())

        for txn in rows:
            txn.cleared = True
            txn.reconciled = True
        await db.flush()

        cleared_query = (
            select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                    BudgetTransaction.cleared == True,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )
        cleared_total = (await db.execute(cleared_query)).scalar() or 0

        adjustment_amount = statement_balance - cleared_total
        adjustment_id = None
        if adjustment_amount != 0:
            today = date.today()
            from app.services.budget.month_locking_service import MonthLockingService
            await MonthLockingService.validate_month_not_closed(
                db, family_id, date(today.year, today.month, 1)
            )
            adj = BudgetTransaction(
                family_id=family_id,
                account_id=account_id,
                date=today,
                amount=adjustment_amount,
                notes="Ajuste de Conciliación",
                cleared=True,
                reconciled=True,
            )
            db.add(adj)
            await db.flush()
            adjustment_id = adj.id

        await db.commit()
        return {
            "reconciled_count": len(rows),
            "adjustment_amount": adjustment_amount,
            "adjustment_transaction_id": adjustment_id,
        }
