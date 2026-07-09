"""
Transaction Service

Business logic for budget transaction operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, update as sql_update
from typing import List, Optional
from datetime import date, datetime, timezone
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
        user_id: Optional[UUID] = None,
    ) -> BudgetTransaction:
        """
        Create a new transaction.

        Args:
            db: Database session
            family_id: Family ID
            data: Transaction creation data
            user_id: Authenticated user creating the transaction; stamped
                as ``created_by_id`` for the per-user last-used account
                fallback in AccountMatchingService. Optional to keep
                test callers and legacy paths working.

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
            # Scanner v2 fields (forwarded by ReceiptDraftService.approve
            # so the v2 metadata isn't dropped on the floor when a draft
            # is promoted to a real transaction).
            card_last4=getattr(data, "card_last4", None),
            iva_cents=getattr(data, "iva_cents", None),
            created_by_id=user_id,
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

        # Category learning (Actual-style, on by default): when a category is
        # assigned to a transaction that has a payee, remember it as that
        # payee's default so future scans/imports inherit it. Last write wins
        # — the user's most recent correction is the best signal.
        new_cat = update_data.get("category_id")
        eff_payee_id = update_data.get("payee_id", existing_txn.payee_id)
        if new_cat and eff_payee_id:
            from app.models.budget import BudgetPayee
            payee = await db.get(BudgetPayee, eff_payee_id)
            if payee is not None and payee.family_id == family_id:
                payee.default_category_id = new_cat

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
        limit: Optional[int] = None,
        offset: Optional[int] = None,
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
        if limit:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

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
        user_id: Optional[UUID] = None,
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
            created_by_id=user_id,
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
                created_by_id=user_id,
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
        user_id: Optional[UUID] = None,
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

        # Soft-delete existing children in a single UPDATE; matches the
        # deleted_at convention used everywhere else and keeps the audit
        # trail of replaced legs.
        await db.execute(
            sql_update(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.parent_id == parent_id,
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.now(timezone.utc))
        )
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
                created_by_id=user_id,
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

        # Phase 1: coerce all string UUIDs up front so the dict is fully
        # normalised before any DB call. Otherwise a validation failure on
        # field N could leave field N-1 already mutated in-place.
        for field in ("category_id", "payee_id"):
            value = filtered.get(field)
            if value is not None and isinstance(value, str):
                filtered[field] = UUID(value)

        # Phase 2: verify FK targets belong to this family. Either both pass
        # or we raise before any transaction is mutated.
        if filtered.get("category_id") is not None:
            from app.services.budget.category_service import CategoryService
            await CategoryService.get_by_id(db, filtered["category_id"], family_id)
        if filtered.get("payee_id") is not None:
            from app.services.budget.payee_service import PayeeService
            await PayeeService.get_by_id(db, filtered["payee_id"], family_id)

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
        user_id: Optional[UUID] = None,
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
                created_by_id=user_id,
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

    # ------------------------------------------------------------------
    # Recurring-charge detection (P2)
    # ------------------------------------------------------------------
    # Scan the family's transaction history for repeating
    # (payee, ~amount, ~regular cadence) series — the forgotten streaming
    # subscription, the monthly gym, rent — and surface them as candidates
    # the parent can promote to a BudgetRecurringTransaction with one click.
    # Pure history analysis: no new tables, no AI. Family-scoped.

    # Cadence bands: (name, expected gap in days, tolerance in days). A series
    # is classified by its average inter-charge gap; every gap must also fall
    # inside a generous window (± 2× tolerance) so irregular one-off clusters
    # are rejected rather than mislabeled.
    _CADENCE_BANDS = (
        ("weekly", 7, 2),
        ("biweekly", 14, 3),
        ("monthly", 30, 6),
        ("yearly", 365, 25),
    )

    @classmethod
    async def detect_recurring_candidates(
        cls,
        db: AsyncSession,
        family_id: UUID,
        *,
        min_occurrences: int = 3,
        amount_tolerance: float = 0.05,
        lookback_days: int = 400,
    ) -> List[dict]:
        """Detect likely recurring charges from transaction history.

        Groups a family's transactions by payee, clusters each payee's charges
        by near-equal amount, and flags clusters that repeat on a regular
        cadence (weekly / biweekly / monthly / yearly) with at least
        ``min_occurrences`` charges. One-off or irregular spending is ignored.

        Payees that already have an active recurring template are skipped so we
        never suggest a duplicate.

        Returns a list of candidate dicts sorted by number of occurrences:
        ``{payee_id, payee_name, amount_cents, cadence, occurrences,
        avg_interval_days, last_date, next_estimated_date, account_id,
        category_id}``.
        """
        from collections import defaultdict
        from datetime import timedelta
        from app.models.budget import BudgetPayee, BudgetRecurringTransaction

        # Payees already covered by an active recurring template → skip.
        covered_q = select(BudgetRecurringTransaction.payee_id).where(
            and_(
                BudgetRecurringTransaction.family_id == family_id,
                BudgetRecurringTransaction.is_active == True,  # noqa: E712
                BudgetRecurringTransaction.payee_id.isnot(None),
            )
        )
        covered = {
            pid for pid in (await db.execute(covered_q)).scalars().all() if pid is not None
        }

        since = date.today() - timedelta(days=lookback_days)
        txn_q = (
            select(BudgetTransaction, BudgetPayee.name)
            .join(BudgetPayee, BudgetTransaction.payee_id == BudgetPayee.id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id.isnot(None),
                    BudgetTransaction.deleted_at.is_(None),
                    BudgetTransaction.is_parent == False,  # noqa: E712
                    BudgetTransaction.date >= since,
                )
            )
            .order_by(BudgetTransaction.payee_id, BudgetTransaction.date.asc())
        )
        rows = (await db.execute(txn_q)).all()

        by_payee: dict = defaultdict(list)
        for txn, payee_name in rows:
            if txn.payee_id in covered:
                continue
            by_payee[(txn.payee_id, payee_name)].append(txn)

        candidates: List[dict] = []
        for (payee_id, payee_name), txns in by_payee.items():
            if len(txns) < min_occurrences:
                continue
            for cluster in cls._cluster_by_amount(txns, amount_tolerance):
                if len(cluster) < min_occurrences:
                    continue
                analysis = cls._analyze_cadence(cluster)
                if analysis is None:
                    continue
                analysis["payee_id"] = payee_id
                analysis["payee_name"] = payee_name
                candidates.append(analysis)

        candidates.sort(key=lambda c: c["occurrences"], reverse=True)
        return candidates

    @staticmethod
    def _cluster_by_amount(txns: List, tolerance: float) -> List[List]:
        """Greedily cluster transactions whose absolute amounts are near-equal.

        Ordered ascending by |amount|; a new cluster starts whenever a charge
        exceeds the cluster's smallest charge by more than ``tolerance`` (with a
        100-cent floor so tiny charges still cluster). Subscription charges are
        typically identical, so this reliably keeps a payee's Netflix charges
        together while separating a one-off large purchase to the same payee.
        """
        ordered = sorted(txns, key=lambda t: abs(t.amount))
        clusters: List[List] = []
        current: List = []
        ref: Optional[int] = None
        for t in ordered:
            amt = abs(t.amount)
            if ref is None:
                current = [t]
                ref = amt
                continue
            tol = max(int(ref * tolerance), 100)
            if amt - ref <= tol:
                current.append(t)
            else:
                clusters.append(current)
                current = [t]
                ref = amt
        if current:
            clusters.append(current)
        return clusters

    @classmethod
    def _analyze_cadence(cls, cluster: List) -> Optional[dict]:
        """Classify a same-amount cluster's cadence, or None if irregular.

        Returns the candidate payload (minus payee identity) when the cluster's
        inter-charge gaps look like a regular weekly/biweekly/monthly/yearly
        schedule; None otherwise.
        """
        import statistics
        from collections import Counter
        from datetime import timedelta

        dates = sorted(t.date for t in cluster)
        gaps = [
            (dates[i] - dates[i - 1]).days for i in range(1, len(dates))
        ]
        gaps = [g for g in gaps if g > 0]
        if len(gaps) < 2:
            return None

        avg = sum(gaps) / len(gaps)
        cadence = center = tol = None
        for name, expected, band in cls._CADENCE_BANDS:
            if abs(avg - expected) <= band:
                cadence, center, tol = name, expected, band
                break
        if cadence is None:
            return None

        # Regularity guard: reject clusters where any single gap is wildly off
        # the cadence even though the average happens to land in-band.
        window = tol * 2
        if not all(center - window <= g <= center + window for g in gaps):
            return None

        amounts = [abs(t.amount) for t in cluster]
        median_amt = int(round(statistics.median(amounts)))
        expense_leaning = sum(1 for t in cluster if t.amount < 0) >= len(cluster) / 2
        amount_cents = -median_amt if expense_leaning else median_amt

        cat_counts = Counter(
            t.category_id for t in cluster if t.category_id is not None
        )
        category_id = cat_counts.most_common(1)[0][0] if cat_counts else None

        last_txn = max(cluster, key=lambda t: t.date)
        next_estimated = last_txn.date + timedelta(days=int(round(avg)))

        return {
            "occurrences": len(cluster),
            "amount_cents": amount_cents,
            "cadence": cadence,
            "avg_interval_days": round(avg, 1),
            "last_date": last_txn.date,
            "next_estimated_date": next_estimated,
            "account_id": last_txn.account_id,
            "category_id": category_id,
        }
