"""
Tag Service

CRUD operations for budget tags and transaction-tag associations.
"""

from typing import List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete as sql_delete

from app.models.budget import BudgetTag, BudgetTransactionTag, BudgetTransaction
from app.schemas.budget import TagCreate, TagUpdate, TagResponse
from app.services.base_service import BaseFamilyService
from app.core.exceptions import NotFoundException, ValidationException


class TagService(BaseFamilyService[BudgetTag]):
    """Service for tag operations."""

    model = BudgetTag

    @classmethod
    async def create(
        cls,
        db: AsyncSession,
        family_id: UUID,
        data: TagCreate,
    ) -> BudgetTag:
        """Create a new tag."""
        tag = BudgetTag(
            family_id=family_id,
            name=data.name,
            color=data.color,
        )
        db.add(tag)
        await db.commit()
        await db.refresh(tag)
        return tag

    @classmethod
    async def update(
        cls,
        db: AsyncSession,
        tag_id: UUID,
        family_id: UUID,
        data: TagUpdate,
    ) -> BudgetTag:
        """Update a tag."""
        update_data = data.model_dump(exclude_unset=True)
        return await cls.update_by_id(db, tag_id, family_id, update_data)

    @classmethod
    async def set_transaction_tags(
        cls,
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
        tag_ids: List[UUID],
    ) -> List[BudgetTag]:
        """Set tags for a transaction (replaces existing tags)."""
        # Verify transaction exists and belongs to family
        txn = await db.scalar(
            select(BudgetTransaction).where(
                and_(
                    BudgetTransaction.id == transaction_id,
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )
        if not txn:
            raise NotFoundException("Transaction not found")

        # Verify all tags belong to family
        if tag_ids:
            result = await db.execute(
                select(BudgetTag).where(
                    and_(
                        BudgetTag.id.in_(tag_ids),
                        BudgetTag.family_id == family_id,
                    )
                )
            )
            found_tags = list(result.scalars().all())
            found_ids = {t.id for t in found_tags}
            missing = set(tag_ids) - found_ids
            if missing:
                raise ValidationException(f"Tags not found: {missing}")
        else:
            found_tags = []

        # Delete existing associations
        await db.execute(
            sql_delete(BudgetTransactionTag).where(
                BudgetTransactionTag.transaction_id == transaction_id
            )
        )

        # Insert new associations
        for tag_id in tag_ids:
            db.add(BudgetTransactionTag(
                transaction_id=transaction_id,
                tag_id=tag_id,
            ))

        await db.commit()
        return found_tags

    @classmethod
    async def get_transaction_tags(
        cls,
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
    ) -> List[BudgetTag]:
        """Get all tags for a transaction."""
        # Verify transaction belongs to family
        txn = await db.scalar(
            select(BudgetTransaction).where(
                and_(
                    BudgetTransaction.id == transaction_id,
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.deleted_at.is_(None),
                )
            )
        )
        if not txn:
            raise NotFoundException("Transaction not found")

        result = await db.execute(
            select(BudgetTag)
            .join(BudgetTransactionTag, BudgetTransactionTag.tag_id == BudgetTag.id)
            .where(BudgetTransactionTag.transaction_id == transaction_id)
        )
        return list(result.scalars().all())
