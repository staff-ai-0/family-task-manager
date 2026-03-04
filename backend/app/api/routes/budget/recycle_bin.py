"""
Recycle Bin routes

Endpoints for managing soft-deleted budget items (transactions, accounts, categories, groups).
Only accessible to parents.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.recycle_bin_service import RecycleBinService
from app.models import User

router = APIRouter()


@router.get("/", response_model=dict)
async def list_deleted_items(
    item_type: Optional[str] = Query(None, description="Filter by type: transaction, account, category, or category_group"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    List all deleted items in recycle bin (parents only).
    
    Returns items grouped by type or filtered by specific type.
    """
    family_id = to_uuid_required(current_user.family_id)
    
    # Get deleted items
    deleted_items = await RecycleBinService.list_deleted_items(
        db, 
        family_id, 
        item_type=item_type
    )
    
    return {
        "items": deleted_items,
        "total": len(deleted_items),
    }


@router.post("/transactions/{transaction_id}/restore", status_code=status.HTTP_200_OK)
async def restore_transaction(
    transaction_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Restore a deleted transaction to active (parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    transaction = await RecycleBinService.restore_transaction(
        db, family_id, transaction_id
    )
    
    return {
        "success": True,
        "message": f"Transaction {transaction_id} restored",
        "item": {
            "id": str(transaction.id),
            "type": "transaction",
            "restored_at": transaction.updated_at.isoformat(),
        },
    }


@router.post("/accounts/{account_id}/restore", status_code=status.HTTP_200_OK)
async def restore_account(
    account_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Restore a deleted account to active (parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    account = await RecycleBinService.restore_account(
        db, family_id, account_id
    )
    
    return {
        "success": True,
        "message": f"Account {account_id} restored",
        "item": {
            "id": str(account.id),
            "type": "account",
            "name": account.name,
            "restored_at": account.updated_at.isoformat(),
        },
    }


@router.post("/categories/{category_id}/restore", status_code=status.HTTP_200_OK)
async def restore_category(
    category_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Restore a deleted category to active (parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    category = await RecycleBinService.restore_category(
        db, family_id, category_id
    )
    
    return {
        "success": True,
        "message": f"Category {category_id} restored",
        "item": {
            "id": str(category.id),
            "type": "category",
            "name": category.name,
            "restored_at": category.updated_at.isoformat(),
        },
    }


@router.post("/category-groups/{group_id}/restore", status_code=status.HTTP_200_OK)
async def restore_category_group(
    group_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Restore a deleted category group to active (parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    group = await RecycleBinService.restore_category_group(
        db, family_id, group_id
    )
    
    return {
        "success": True,
        "message": f"Category Group {group_id} restored",
        "item": {
            "id": str(group.id),
            "type": "category_group",
            "name": group.name,
            "restored_at": group.updated_at.isoformat(),
        },
    }


@router.delete("/transactions/{transaction_id}/permanently", status_code=status.HTTP_200_OK)
async def permanently_delete_transaction(
    transaction_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a transaction (cannot be undone, parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    await RecycleBinService.permanently_delete_transaction(
        db, family_id, transaction_id
    )
    
    return {
        "success": True,
        "message": f"Transaction {transaction_id} permanently deleted",
    }


@router.delete("/accounts/{account_id}/permanently", status_code=status.HTTP_200_OK)
async def permanently_delete_account(
    account_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete an account (cannot be undone, parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    await RecycleBinService.permanently_delete_account(
        db, family_id, account_id
    )
    
    return {
        "success": True,
        "message": f"Account {account_id} permanently deleted",
    }


@router.delete("/categories/{category_id}/permanently", status_code=status.HTTP_200_OK)
async def permanently_delete_category(
    category_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a category (cannot be undone, parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    await RecycleBinService.permanently_delete_category(
        db, family_id, category_id
    )
    
    return {
        "success": True,
        "message": f"Category {category_id} permanently deleted",
    }


@router.delete("/category-groups/{group_id}/permanently", status_code=status.HTTP_200_OK)
async def permanently_delete_category_group(
    group_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a category group (cannot be undone, parents only)"""
    family_id = to_uuid_required(current_user.family_id)
    
    await RecycleBinService.permanently_delete_category_group(
        db, family_id, group_id
    )
    
    return {
        "success": True,
        "message": f"Category Group {group_id} permanently deleted",
    }


@router.delete("/", status_code=status.HTTP_200_OK)
async def empty_recycle_bin(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Empty recycle bin by permanently deleting all items older than 30 days (parents only).
    """
    family_id = to_uuid_required(current_user.family_id)
    
    count = await RecycleBinService.empty_recycle_bin(db, family_id)
    
    return {
        "success": True,
        "message": f"Recycle bin emptied, {count} items permanently deleted",
        "items_deleted": count,
    }
