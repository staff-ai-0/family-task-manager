"""
Account Service

Business logic for budget account operations.
"""

from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from typing import List, Optional, Dict
from uuid import UUID

from app.models.budget import BudgetAccount, BudgetTransaction
from app.schemas.budget import AccountCreate, AccountUpdate
from app.services.base_service import BaseFamilyService


class AccountService(BaseFamilyService[BudgetAccount]):
    """Service for budget account operations"""

    model = BudgetAccount

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: AccountCreate,
    ) -> BudgetAccount:
        """
        Create a new account.

        Args:
            db: Database session
            family_id: Family ID
            data: Account creation data

        Returns:
            Created account
        """
        account = BudgetAccount(
            family_id=family_id,
            name=data.name,
            type=data.type,
            offbudget=data.offbudget,
            closed=data.closed,
            notes=data.notes,
            sort_order=data.sort_order,
        )

        db.add(account)
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
        return await cls.update_by_id(db, account_id, family_id, update_data)

    @classmethod
    async def list_by_type(
        cls,
        db: AsyncSession,
        family_id: UUID,
        account_type: str,
        include_closed: bool = False,
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
                )
            )
            .order_by(BudgetAccount.sort_order, BudgetAccount.name)
        )

        if not include_closed:
            query = query.where(BudgetAccount.closed == False)

        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def list_budget_accounts(
        cls,
        db: AsyncSession,
        family_id: UUID,
        include_closed: bool = False,
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
                )
            )
            .order_by(BudgetAccount.sort_order, BudgetAccount.name)
        )

        if not include_closed:
            query = query.where(BudgetAccount.closed == False)

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
    async def get_balances_for_all_accounts(
        cls,
        db: AsyncSession,
        family_id: UUID,
        as_of_date: Optional[date] = None,
        include_closed: bool = False,
    ) -> Dict[UUID, Dict[str, int]]:
        """
        Get balances for all accounts in the family.
        
        Args:
            db: Database session
            family_id: Family ID
            as_of_date: Calculate balances as of this date
            include_closed: Whether to include closed accounts
        
        Returns:
            Dict mapping account_id to balance info
        """
        accounts = await cls.list_all(db, family_id)
        if not include_closed:
            accounts = [a for a in accounts if not a.closed]
        
        balances = {}
        for account in accounts:
            balances[account.id] = await cls.get_balance(
                db, account.id, family_id, as_of_date
            )
        
        return balances
