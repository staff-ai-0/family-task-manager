"""
Account Service

Business logic for budget account operations.
"""

from datetime import date, datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func, update as sql_update
from typing import List, Optional, Dict
from uuid import UUID

from app.models.budget import BudgetAccount, BudgetTransaction
from app.schemas.budget import AccountCreate, AccountUpdate
from app.services.base_service import BaseFamilyService
from app.core.exceptions import ValidationError
from app.core.time_utils import utc_today


class AccountService(BaseFamilyService[BudgetAccount]):
    """Service for budget account operations"""

    model = BudgetAccount

    @classmethod
    async def delete_by_id(
        cls,
        db: AsyncSession,
        entity_id: UUID,
        family_id: UUID,
    ) -> None:
        """SOFT delete the account and cascade-soft-delete its live
        transactions (same one-timestamp pattern as group→categories).

        Overrides BaseService.delete_by_id, which hard-deletes — that made
        DELETE /accounts/{id} destroy the account AND its transaction history
        with no recycle-bin recovery. RecycleBinService.restore_account
        un-deletes the cascaded transactions by matching this timestamp.
        """
        entity = await cls.get_by_id(db, entity_id, family_id)
        now = datetime.now(timezone.utc)
        entity.deleted_at = now
        await db.execute(
            sql_update(BudgetTransaction)
            .where(
                BudgetTransaction.account_id == entity.id,
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        await db.commit()

    @classmethod
    async def _existing_family_currency(
        cls,
        db: AsyncSession,
        family_id: UUID,
        exclude_account_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """Return the currency in use by any non-deleted account in the family,
        or None when the family has no accounts yet.

        Reports and balance aggregations sum amounts across accounts without
        currency conversion, so families must use a single currency.

        exclude_account_id lets the update path skip the row being changed,
        so a sole-account currency change is permitted (no other account is
        anchored to the old currency).

        ORDER BY created_at, id makes the result deterministic if legacy data
        ever ends up with mixed currencies — same anchor row every call.
        """
        conditions = [
            BudgetAccount.family_id == family_id,
            BudgetAccount.deleted_at.is_(None),
        ]
        if exclude_account_id is not None:
            conditions.append(BudgetAccount.id != exclude_account_id)
        q = (
            select(BudgetAccount.currency)
            .where(and_(*conditions))
            .order_by(BudgetAccount.created_at, BudgetAccount.id)
            .limit(1)
        )
        return (await db.execute(q)).scalar_one_or_none()

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: AccountCreate,
        user_id: Optional[UUID] = None,
    ) -> BudgetAccount:
        """
        Create a new account.

        If data.starting_balance != 0, a synthetic "Starting Balance" transaction
        is automatically created so the account balance is correct from day one.
        This mirrors the Actual Budget approach.

        Args:
            db: Database session
            family_id: Family ID
            data: Account creation data

        Returns:
            Created account
        """
        existing_currency = await cls._existing_family_currency(db, family_id)
        if existing_currency is not None and existing_currency != data.currency:
            raise ValidationError(
                f"Account currency {data.currency!r} does not match the family's "
                f"existing currency {existing_currency!r}. Reports do not convert "
                f"across currencies."
            )

        account = BudgetAccount(
            family_id=family_id,
            name=data.name,
            type=data.type,
            offbudget=data.offbudget,
            closed=data.closed,
            notes=data.notes,
            sort_order=data.sort_order,
            starting_balance=data.starting_balance,
            currency=data.currency,
        )

        db.add(account)
        await db.flush()  # get account.id without committing yet

        # Auto-create starting balance transaction if non-zero
        if data.starting_balance != 0:
            starting_txn = BudgetTransaction(
                family_id=family_id,
                account_id=account.id,
                date=utc_today(),
                amount=data.starting_balance,
                notes="Starting Balance",
                cleared=True,
                reconciled=False,
                is_parent=False,
                created_by_id=user_id,
            )
            db.add(starting_txn)

        await db.commit()
        await db.refresh(account)
        return account

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        data: AccountUpdate,
    ) -> BudgetAccount:
        """
        Update an account.

        Args:
            db: Database session
            account_id: Account ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated account
        """
        update_data = data.model_dump(exclude_unset=True)
        if "currency" in update_data and update_data["currency"] is not None:
            existing = await cls._existing_family_currency(
                db, family_id, exclude_account_id=account_id
            )
            if existing is not None and existing != update_data["currency"]:
                raise ValidationError(
                    f"Cannot change account currency to {update_data['currency']!r}; "
                    f"family already uses {existing!r}. Reports do not convert "
                    f"across currencies."
                )
        return await cls.update_by_id(db, account_id, family_id, update_data)

    @classmethod
    async def list_for_family(
        cls,
        db: AsyncSession,
        family_id: UUID,
        include_closed: bool = False,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetAccount]:
        """List accounts with the closed filter applied at the SQL level so
        pagination is stable. The base class list_by_family ignores closed.
        """
        query = (
            select(BudgetAccount)
            .where(
                and_(
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
            .order_by(BudgetAccount.sort_order, BudgetAccount.name)
        )
        if not include_closed:
            query = query.where(BudgetAccount.closed == False)
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        return list((await db.execute(query)).scalars().all())

    @classmethod
    async def list_by_type(
        cls,
        db: AsyncSession,
        family_id: UUID,
        account_type: str,
        include_closed: bool = False,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetAccount]:
        """
        List accounts by type.

        Args:
            db: Database session
            family_id: Family ID
            account_type: Account type to filter by
            include_closed: Whether to include closed accounts

        Returns:
            List of accounts
        """
        query = (
            select(BudgetAccount)
            .where(
                and_(
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.type == account_type,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
            .order_by(BudgetAccount.sort_order, BudgetAccount.name)
        )

        if not include_closed:
            query = query.where(BudgetAccount.closed == False)
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_budget_accounts(
        cls,
        db: AsyncSession,
        family_id: UUID,
        include_closed: bool = False,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetAccount]:
        """
        List on-budget accounts (excludes tracking/offbudget accounts).

        Args:
            db: Database session
            family_id: Family ID
            include_closed: Whether to include closed accounts

        Returns:
            List of on-budget accounts
        """
        query = (
            select(BudgetAccount)
            .where(
                and_(
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.offbudget == False,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
            .order_by(BudgetAccount.sort_order, BudgetAccount.name)
        )

        if not include_closed:
            query = query.where(BudgetAccount.closed == False)
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def get_balance(
        cls,
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
        as_of_date: Optional[date] = None,
    ) -> Dict[str, int]:
        """
        Calculate account balance.
        
        Balance is the sum of all transaction amounts for this account.
        Positive amounts = income/deposits, Negative amounts = expenses/withdrawals
        
        Args:
            db: Database session
            account_id: Account ID
            family_id: Family ID for verification
            as_of_date: Calculate balance as of this date (inclusive). If None, uses all transactions.
        
        Returns:
            Dict with balance, cleared_balance, and uncleared_balance (all in cents)
        """
        # Verify account belongs to family
        account = await cls.get_by_id(db, account_id, family_id)
        if not account:
            raise ValueError(f"Account {account_id} not found for family {family_id}")
        
        # Build base query for total balance
        balance_query = (
            select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id == account_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )

        # Build query for cleared balance (cleared transactions only)
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
        
        # Add date filter if specified
        if as_of_date:
            balance_query = balance_query.where(BudgetTransaction.date <= as_of_date)
            cleared_query = cleared_query.where(BudgetTransaction.date <= as_of_date)
        
        # Execute queries
        total_result = await db.execute(balance_query)
        total_balance = total_result.scalar() or 0
        
        cleared_result = await db.execute(cleared_query)
        cleared_balance = cleared_result.scalar() or 0
        
        uncleared_balance = total_balance - cleared_balance
        
        return {
            "balance": total_balance,
            "cleared_balance": cleared_balance,
            "uncleared_balance": uncleared_balance,
        }

    @classmethod
    async def get_total_on_budget_balance(
        cls,
        db: AsyncSession,
        family_id: UUID,
        as_of_date: Optional[date] = None,
    ) -> int:
        """
        Calculate the total balance across ALL on-budget (non-offbudget, non-closed) accounts.

        This is the core figure for envelope budgeting — the total real money available
        to be assigned to categories. Mirrors Actual Budget's "Available Funds" total.

        Formula:
            SUM of all transaction amounts in on-budget accounts up to as_of_date

        Args:
            db: Database session
            family_id: Family ID
            as_of_date: Calculate balance as of this date (inclusive). Defaults to today.

        Returns:
            Total balance in cents
        """
        # Sub-query: IDs of all on-budget, non-closed accounts for this family
        on_budget_accounts_query = (
            select(BudgetAccount.id)
            .where(
                and_(
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.offbudget == False,
                    BudgetAccount.closed == False,
                    BudgetAccount.deleted_at.is_(None),
                )
            )
        )

        # Sum all transactions in those accounts
        balance_query = (
            select(func.coalesce(func.sum(BudgetTransaction.amount), 0))
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.account_id.in_(on_budget_accounts_query),
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )

        if as_of_date:
            balance_query = balance_query.where(BudgetTransaction.date <= as_of_date)

        result = await db.execute(balance_query)
        return result.scalar() or 0

    @classmethod
    async def get_balances_for_accounts(
        cls,
        db: AsyncSession,
        account_ids: list,
        family_id: UUID,
        as_of_date: Optional[date] = None,
    ) -> Dict[UUID, Dict[str, int]]:
        """Batched balances for the given accounts in TWO grouped queries
        (replaces the per-account N+1). Same shape and values as get_balance;
        sums cast to int so a Decimal never serializes as a JSON string."""
        if not account_ids:
            return {}

        def _sum_query(cleared_only: bool):
            conds = [
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.account_id.in_(account_ids),
                BudgetTransaction.deleted_at.is_(None),
            ]
            if cleared_only:
                conds.append(BudgetTransaction.cleared == True)  # noqa: E712
            if as_of_date:
                conds.append(BudgetTransaction.date <= as_of_date)
            return (
                select(
                    BudgetTransaction.account_id,
                    func.coalesce(func.sum(BudgetTransaction.amount), 0),
                )
                .where(and_(*conds))
                .group_by(BudgetTransaction.account_id)
            )

        total = {r[0]: int(r[1] or 0) for r in (await db.execute(_sum_query(False))).all()}
        cleared = {r[0]: int(r[1] or 0) for r in (await db.execute(_sum_query(True))).all()}

        out: Dict[UUID, Dict[str, int]] = {}
        for aid in account_ids:
            b = total.get(aid, 0)
            c = cleared.get(aid, 0)
            out[aid] = {"balance": b, "cleared_balance": c, "uncleared_balance": b - c}
        return out

    @classmethod
    async def get_balances_for_all_accounts(
        cls,
        db: AsyncSession,
        family_id: UUID,
        as_of_date: Optional[date] = None,
        include_closed: bool = False,
    ) -> Dict[UUID, Dict[str, int]]:
        """Batched balances for all of the family's accounts (no N+1)."""
        accounts = await cls.list_budget_accounts(db, family_id, include_closed=include_closed)
        balances = await cls.get_balances_for_accounts(
            db, [account.id for account in accounts], family_id, as_of_date
        )
        
        return balances
