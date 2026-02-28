"""
Account Service

Business logic for budget account operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List
from uuid import UUID

from app.models.budget import BudgetAccount
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
