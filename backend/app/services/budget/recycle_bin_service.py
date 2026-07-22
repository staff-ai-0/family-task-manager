"""
Recycle Bin Service

Service for managing soft-deleted budget items (transactions, accounts, categories).
Handles restoration, permanent deletion, and listing of deleted items.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional, Type, TypeVar
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.models.budget import (
    BudgetTransaction,
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
)
from app.core.exceptions import NotFoundException

T = TypeVar('T')
SoftDeletable = TypeVar(
    'SoftDeletable', BudgetTransaction, BudgetAccount, BudgetCategory, BudgetCategoryGroup
)


class RecycleBinService:
    """Service for managing soft-deleted budget items"""
    
    # Supported models for recycle bin
    SUPPORTED_MODELS = {
        'transaction': BudgetTransaction,
        'account': BudgetAccount,
        'category': BudgetCategory,
        'category_group': BudgetCategoryGroup,
    }
    
    @staticmethod
    async def list_deleted_items(
        db: AsyncSession,
        family_id: UUID,
        item_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """
        List all soft-deleted items for a family.
        
        Args:
            db: Database session
            family_id: Family ID
            item_type: Filter by type ('transaction', 'account', 'category', 'category_group')
            limit: Maximum items to return
            offset: Pagination offset
            
        Returns:
            Dict with deleted items grouped by type
        """
        result = {
            'transactions': [],
            'accounts': [],
            'categories': [],
            'category_groups': [],
            'total_deleted': 0,
        }
        
        # Get deleted transactions
        # parent_id IS NULL filters out replaced split-child legs that were
        # soft-deleted by replace_split_children. Those rows are an internal
        # audit trail of the split's edit history — they are not user-visible
        # transactions and should not clutter the recycle bin.
        if not item_type or item_type == 'transaction':
            stmt = (
                select(BudgetTransaction)
                .where(
                    BudgetTransaction.family_id == family_id,
                    BudgetTransaction.deleted_at.is_not(None),
                    BudgetTransaction.parent_id.is_(None),
                )
                .order_by(desc(BudgetTransaction.deleted_at))
                .limit(limit)
                .offset(offset)
            )
            transactions = await db.scalars(stmt)
            result['transactions'] = list(transactions)
        
        # Get deleted accounts
        if not item_type or item_type == 'account':
            stmt = (
                select(BudgetAccount)
                .where(
                    BudgetAccount.family_id == family_id,
                    BudgetAccount.deleted_at.is_not(None),
                )
                .order_by(desc(BudgetAccount.deleted_at))
                .limit(limit)
                .offset(offset)
            )
            accounts = await db.scalars(stmt)
            result['accounts'] = list(accounts)
        
        # Get deleted categories
        if not item_type or item_type == 'category':
            stmt = (
                select(BudgetCategory)
                .where(
                    BudgetCategory.family_id == family_id,
                    BudgetCategory.deleted_at.is_not(None),
                )
                .order_by(desc(BudgetCategory.deleted_at))
                .limit(limit)
                .offset(offset)
            )
            categories = await db.scalars(stmt)
            result['categories'] = list(categories)
        
        # Get deleted category groups
        if not item_type or item_type == 'category_group':
            stmt = (
                select(BudgetCategoryGroup)
                .where(
                    BudgetCategoryGroup.family_id == family_id,
                    BudgetCategoryGroup.deleted_at.is_not(None),
                )
                .order_by(desc(BudgetCategoryGroup.deleted_at))
                .limit(limit)
                .offset(offset)
            )
            category_groups = await db.scalars(stmt)
            result['category_groups'] = list(category_groups)
        
        # Calculate total deleted count
        result['total_deleted'] = (
            len(result['transactions']) + 
            len(result['accounts']) + 
            len(result['categories']) + 
            len(result['category_groups'])
        )
        
        return result
    
    @staticmethod
    async def _restore(
        db: AsyncSession,
        model: Type[SoftDeletable],
        item_id: UUID,
        family_id: UUID,
        not_found_msg: str,
    ) -> SoftDeletable:
        """Shared restore body for every recycle-bin-eligible model."""
        stmt = select(model).where(
            model.id == item_id,
            model.family_id == family_id,
            model.deleted_at.is_not(None),
        )
        item = await db.scalar(stmt)

        if not item:
            raise NotFoundException(not_found_msg)

        item.deleted_at = None
        item.deleted_by_id = None
        await db.commit()
        # updated_at has an `onupdate=func.now()` SQL-computed default, which
        # SQLAlchemy marks expired after flush regardless of expire_on_commit
        # — every restore_* route reads it (`restored_at`) right after this
        # returns, and an expired attribute accessed outside an await
        # context 500s with MissingGreenlet. Refresh so it's already loaded.
        await db.refresh(item)

        return item

    @staticmethod
    async def _permanently_delete(
        db: AsyncSession,
        model: Type[SoftDeletable],
        item_id: UUID,
        family_id: UUID,
        not_found_msg: str,
    ) -> SoftDeletable:
        """Shared hard-delete lookup+guard; caller commits (account cascades
        its transactions into the same commit)."""
        stmt = select(model).where(
            model.id == item_id,
            model.family_id == family_id,
            model.deleted_at.is_not(None),
        )
        item = await db.scalar(stmt)

        if not item:
            raise NotFoundException(not_found_msg)

        await db.delete(item)
        return item

    @staticmethod
    async def restore_transaction(
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
    ) -> BudgetTransaction:
        """Restore a soft-deleted transaction from recycle bin"""
        return await RecycleBinService._restore(
            db, BudgetTransaction, transaction_id, family_id, "Deleted transaction not found"
        )

    @staticmethod
    async def restore_account(
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
    ) -> BudgetAccount:
        """Restore a soft-deleted account from recycle bin"""
        return await RecycleBinService._restore(
            db, BudgetAccount, account_id, family_id, "Deleted account not found"
        )

    @staticmethod
    async def restore_category(
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> BudgetCategory:
        """Restore a soft-deleted category from recycle bin"""
        return await RecycleBinService._restore(
            db, BudgetCategory, category_id, family_id, "Deleted category not found"
        )

    @staticmethod
    async def restore_category_group(
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
    ) -> BudgetCategoryGroup:
        """Restore a soft-deleted category group from recycle bin"""
        return await RecycleBinService._restore(
            db, BudgetCategoryGroup, group_id, family_id, "Deleted category group not found"
        )

    @staticmethod
    async def permanently_delete_transaction(
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted transaction"""
        await RecycleBinService._permanently_delete(
            db, BudgetTransaction, transaction_id, family_id, "Deleted transaction not found"
        )
        await db.commit()

    @staticmethod
    async def permanently_delete_account(
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted account (and its deleted transactions)"""
        await RecycleBinService._permanently_delete(
            db, BudgetAccount, account_id, family_id, "Deleted account not found"
        )

        # Permanently delete associated transactions too
        stmt_txns = select(BudgetTransaction).where(
            BudgetTransaction.account_id == account_id,
            BudgetTransaction.deleted_at.is_not(None),
        )
        transactions = await db.scalars(stmt_txns)
        for txn in transactions:
            await db.delete(txn)

        await db.commit()

    @staticmethod
    async def permanently_delete_category(
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted category"""
        await RecycleBinService._permanently_delete(
            db, BudgetCategory, category_id, family_id, "Deleted category not found"
        )
        await db.commit()

    @staticmethod
    async def permanently_delete_category_group(
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted category group"""
        await RecycleBinService._permanently_delete(
            db, BudgetCategoryGroup, group_id, family_id, "Deleted category group not found"
        )
        await db.commit()

    @staticmethod
    async def empty_recycle_bin(
        db: AsyncSession,
        family_id: UUID,
        days_old: int = 30,
    ) -> dict:
        """
        Permanently delete items older than specified days.
        Default 30 days to match requirements.

        Filters the cutoff in SQL (WHERE deleted_at < cutoff) instead of
        loading every soft-deleted row per family per entity type into
        Python and filtering there — that scales badly for a family with a
        large recycle bin.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)

        count = {
            'transactions': 0,
            'accounts': 0,
            'categories': 0,
            'category_groups': 0,
        }
        count_keys = {
            BudgetTransaction: 'transactions',
            BudgetAccount: 'accounts',
            BudgetCategory: 'categories',
            BudgetCategoryGroup: 'category_groups',
        }

        for model in RecycleBinService.SUPPORTED_MODELS.values():
            stmt = select(model).where(
                model.family_id == family_id,
                model.deleted_at.is_not(None),
                model.deleted_at < cutoff,
            )
            old_items = await db.scalars(stmt)
            key = count_keys[model]
            for item in old_items:
                await db.delete(item)
                count[key] += 1

        await db.commit()
        return count
