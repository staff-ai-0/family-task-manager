"""
Payee Service

Business logic for budget payee operations.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update as sql_update
from typing import List, Optional
from uuid import UUID

from app.models.budget import BudgetPayee, BudgetTransaction, BudgetRecurringTransaction
from app.schemas.budget import PayeeCreate, PayeeUpdate, PayeeMergeRequest
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationException


class PayeeService(BaseFamilyService[BudgetPayee]):
    """Service for budget payee operations"""

    model = BudgetPayee

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: PayeeCreate,
    ) -> BudgetPayee:
        """
        Create a new payee.

        Args:
            db: Database session
            family_id: Family ID
            data: Payee creation data

        Returns:
            Created payee
        """
        payee = BudgetPayee(
            family_id=family_id,
            name=data.name,
            notes=data.notes,
            is_favorite=data.is_favorite,
        )

        db.add(payee)
        await db.commit()
        await db.refresh(payee)
        return payee

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        payee_id: UUID,
        family_id: UUID,
        data: PayeeUpdate,
    ) -> BudgetPayee:
        """
        Update a payee.

        Args:
            db: Database session
            payee_id: Payee ID to update
            family_id: Family ID for verification
            data: Update data

        Returns:
            Updated payee
        """
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, payee_id, family_id, update_data)

    @classmethod
    async def get_or_create_by_name(
        cls,
        db: AsyncSession,
        family_id: UUID,
        name: str,
    ) -> BudgetPayee:
        """Return an existing payee with the given name, or create a new one."""
        result = await db.execute(
            select(BudgetPayee).where(
                and_(BudgetPayee.family_id == family_id, BudgetPayee.name == name)
            )
        )
        existing = result.scalars().first()
        if existing:
            return existing
        payee = BudgetPayee(family_id=family_id, name=name)
        db.add(payee)
        await db.commit()
        await db.refresh(payee)
        return payee

    @classmethod
    async def list_by_family_filtered(
        cls,
        db: AsyncSession,
        family_id: UUID,
        favorites_only: bool = False,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[BudgetPayee]:
        """
        List payees for a family with optional favorite filter.

        Args:
            db: Database session
            family_id: Family ID
            favorites_only: If True, only return favorite payees
            limit: Max results
            offset: Pagination offset

        Returns:
            List of payees
        """
        query = select(BudgetPayee).where(BudgetPayee.family_id == family_id)
        if favorites_only:
            query = query.where(BudgetPayee.is_favorite == True)
        query = query.order_by(BudgetPayee.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        if offset:
            query = query.offset(offset)
        result = await db.execute(query)
        return list(result.scalars().all())

    @classmethod
    async def merge(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: PayeeMergeRequest,
    ) -> BudgetPayee:
        """
        Merge source payees into target payee.

        Reassigns all transactions and recurring transactions from source payees
        to the target, then deletes the sources. All in a single transaction.

        Args:
            db: Database session
            family_id: Family ID
            data: Merge request with target_id and source_ids

        Returns:
            The target payee

        Raises:
            ValidationException: If target_id is in source_ids
            NotFoundException: If target or any source not found
        """
        if data.target_id in data.source_ids:
            raise ValidationException("target_id must not be in source_ids")

        # Verify target belongs to family
        target = await cls.get_by_id(db, data.target_id, family_id)

        # Verify all sources belong to family
        for source_id in data.source_ids:
            await cls.get_by_id(db, source_id, family_id)

        # Update transactions: reassign payee_id from sources to target
        await db.execute(
            sql_update(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id.in_(data.source_ids),
                )
            )
            .values(payee_id=data.target_id)
        )

        # Update recurring transactions: reassign payee_id from sources to target
        await db.execute(
            sql_update(BudgetRecurringTransaction)
            .where(
                and_(
                    BudgetRecurringTransaction.family_id == family_id,
                    BudgetRecurringTransaction.payee_id.in_(data.source_ids),
                )
            )
            .values(payee_id=data.target_id)
        )

        # Delete source payees
        for source_id in data.source_ids:
            source = await cls.get_by_id(db, source_id, family_id)
            await db.delete(source)

        await db.commit()
        await db.refresh(target)
        return target

    @classmethod
    async def merge_payees(
        cls,
        db: AsyncSession,
        family_id: UUID,
        source_id: UUID,
        target_id: UUID,
    ) -> dict:
        """Merge a single source payee into target. Returns merge stats."""
        if source_id == target_id:
            raise ValidationException("source and target must differ")

        source = await cls.get_by_id(db, source_id, family_id)
        target = await cls.get_by_id(db, target_id, family_id)

        # Count source transactions before reassignment
        count_q = select(BudgetTransaction).where(
            and_(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.payee_id == source_id,
            )
        )
        merged_count = len(list((await db.execute(count_q)).scalars().all()))

        await db.execute(
            sql_update(BudgetTransaction)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id == source_id,
                )
            )
            .values(payee_id=target_id)
        )

        await db.execute(
            sql_update(BudgetRecurringTransaction)
            .where(
                and_(
                    BudgetRecurringTransaction.family_id == family_id,
                    BudgetRecurringTransaction.payee_id == source_id,
                )
            )
            .values(payee_id=target_id)
        )

        source_name = source.name
        target_name = target.name
        await db.delete(source)
        await db.commit()

        return {
            "merged_count": merged_count,
            "source_name": source_name,
            "target_name": target_name,
        }

    @classmethod
    async def get_last_category(
        cls,
        db: AsyncSession,
        payee_id: UUID,
        family_id: UUID,
    ) -> Optional[UUID]:
        """Return category_id of the most recent transaction for payee, or None."""
        query = (
            select(BudgetTransaction.category_id)
            .where(
                and_(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.payee_id == payee_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
            .order_by(BudgetTransaction.date.desc(), BudgetTransaction.created_at.desc())
            .limit(1)
        )
        result = await db.execute(query)
        return result.scalar_one_or_none()
