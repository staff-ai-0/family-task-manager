"""
Recycle Bin Service

Service for managing soft-deleted budget items (transactions, accounts, categories).
Handles restoration, permanent deletion, and listing of deleted items.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from typing import List, Optional, Type, TypeVar
from datetime import datetime, timezone
from uuid import UUID

from app.models.budget import (
    BudgetTransaction,
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
)
from app.core.exceptions import NotFoundException, ValidationError

T = TypeVar('T')


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
    async def restore_transaction(
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
    ) -> BudgetTransaction:
        """Restore a soft-deleted transaction from recycle bin"""
        stmt = select(BudgetTransaction).where(
            BudgetTransaction.id == transaction_id,
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_not(None),
        )
        transaction = await db.scalar(stmt)
        
        if not transaction:
            raise NotFoundException("Deleted transaction not found")
        
        transaction.deleted_at = None
        transaction.deleted_by_id = None
        await db.commit()
        
        return transaction
    
    @staticmethod
    async def restore_account(
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
    ) -> BudgetAccount:
        """Restore a soft-deleted account from recycle bin"""
        stmt = select(BudgetAccount).where(
            BudgetAccount.id == account_id,
            BudgetAccount.family_id == family_id,
            BudgetAccount.deleted_at.is_not(None),
        )
        account = await db.scalar(stmt)
        
        if not account:
            raise NotFoundException("Deleted account not found")
        
        account.deleted_at = None
        account.deleted_by_id = None
        await db.commit()
        
        return account
    
    @staticmethod
    async def restore_category(
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> BudgetCategory:
        """Restore a soft-deleted category from recycle bin"""
        stmt = select(BudgetCategory).where(
            BudgetCategory.id == category_id,
            BudgetCategory.family_id == family_id,
            BudgetCategory.deleted_at.is_not(None),
        )
        category = await db.scalar(stmt)
        
        if not category:
            raise NotFoundException("Deleted category not found")
        
        category.deleted_at = None
        category.deleted_by_id = None
        await db.commit()
        
        return category
    
    @staticmethod
    async def restore_category_group(
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
    ) -> BudgetCategoryGroup:
        """Restore a soft-deleted category group from recycle bin"""
        stmt = select(BudgetCategoryGroup).where(
            BudgetCategoryGroup.id == group_id,
            BudgetCategoryGroup.family_id == family_id,
            BudgetCategoryGroup.deleted_at.is_not(None),
        )
        group = await db.scalar(stmt)
        
        if not group:
            raise NotFoundException("Deleted category group not found")
        
        group.deleted_at = None
        group.deleted_by_id = None
        await db.commit()
        
        return group
    
    @staticmethod
    async def permanently_delete_transaction(
        db: AsyncSession,
        transaction_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted transaction"""
        stmt = select(BudgetTransaction).where(
            BudgetTransaction.id == transaction_id,
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_not(None),
        )
        transaction = await db.scalar(stmt)
        
        if not transaction:
            raise NotFoundException("Deleted transaction not found")
        
        await db.delete(transaction)
        await db.commit()
    
    @staticmethod
    async def permanently_delete_account(
        db: AsyncSession,
        account_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted account"""
        stmt = select(BudgetAccount).where(
            BudgetAccount.id == account_id,
            BudgetAccount.family_id == family_id,
            BudgetAccount.deleted_at.is_not(None),
        )
        account = await db.scalar(stmt)
        
        if not account:
            raise NotFoundException("Deleted account not found")
        
        # Permanently delete associated transactions too
        stmt_txns = select(BudgetTransaction).where(
            BudgetTransaction.account_id == account_id,
            BudgetTransaction.deleted_at.is_not(None),
        )
        transactions = await db.scalars(stmt_txns)
        for txn in transactions:
            await db.delete(txn)
        
        await db.delete(account)
        await db.commit()
    
    @staticmethod
    async def permanently_delete_category(
        db: AsyncSession,
        category_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted category"""
        stmt = select(BudgetCategory).where(
            BudgetCategory.id == category_id,
            BudgetCategory.family_id == family_id,
            BudgetCategory.deleted_at.is_not(None),
        )
        category = await db.scalar(stmt)
        
        if not category:
            raise NotFoundException("Deleted category not found")
        
        await db.delete(category)
        await db.commit()
    
    @staticmethod
    async def permanently_delete_category_group(
        db: AsyncSession,
        group_id: UUID,
        family_id: UUID,
    ) -> None:
        """Permanently delete a soft-deleted category group"""
        stmt = select(BudgetCategoryGroup).where(
            BudgetCategoryGroup.id == group_id,
            BudgetCategoryGroup.family_id == family_id,
            BudgetCategoryGroup.deleted_at.is_not(None),
        )
        group = await db.scalar(stmt)
        
        if not group:
            raise NotFoundException("Deleted category group not found")
        
        await db.delete(group)
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
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (days_old * 86400)
        
        # Count items to be deleted
        count = {
            'transactions': 0,
            'accounts': 0,
            'categories': 0,
            'category_groups': 0,
        }
        
        # Delete old transactions
        stmt = select(BudgetTransaction).where(
            BudgetTransaction.family_id == family_id,
            BudgetTransaction.deleted_at.is_not(None),
        )
        old_transactions = await db.scalars(stmt)
        for txn in old_transactions:
            if txn.deleted_at and txn.deleted_at.timestamp() < cutoff:
                await db.delete(txn)
                count['transactions'] += 1
        
        # Delete old accounts
        stmt = select(BudgetAccount).where(
            BudgetAccount.family_id == family_id,
            BudgetAccount.deleted_at.is_not(None),
        )
        old_accounts = await db.scalars(stmt)
        for acc in old_accounts:
            if acc.deleted_at and acc.deleted_at.timestamp() < cutoff:
                await db.delete(acc)
                count['accounts'] += 1
        
        # Delete old categories
        stmt = select(BudgetCategory).where(
            BudgetCategory.family_id == family_id,
            BudgetCategory.deleted_at.is_not(None),
        )
        old_categories = await db.scalars(stmt)
        for cat in old_categories:
            if cat.deleted_at and cat.deleted_at.timestamp() < cutoff:
                await db.delete(cat)
                count['categories'] += 1
        
        # Delete old category groups
        stmt = select(BudgetCategoryGroup).where(
            BudgetCategoryGroup.family_id == family_id,
            BudgetCategoryGroup.deleted_at.is_not(None),
        )
        old_groups = await db.scalars(stmt)
        for grp in old_groups:
            if grp.deleted_at and grp.deleted_at.timestamp() < cutoff:
                await db.delete(grp)
                count['category_groups'] += 1
        
        await db.commit()
        return count
