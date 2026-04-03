"""
Tag routes

CRUD endpoints for budget tags and transaction-tag associations.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.tag_service import TagService
from app.schemas.budget import (
    TagCreate,
    TagUpdate,
    TagResponse,
    TransactionTagsUpdate,
)
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[TagResponse])
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all tags for the family"""
    family_id = to_uuid_required(current_user.family_id)
    return await TagService.list_by_family(db, family_id)


@router.post("/", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create_tag(
    data: TagCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new tag (parent only)"""
    return await TagService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    tag_id: UUID,
    data: TagUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a tag (parent only)"""
    return await TagService.update(
        db, tag_id, to_uuid_required(current_user.family_id), data
    )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a tag (parent only)"""
    await TagService.delete_by_id(
        db, tag_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.get("/transactions/{transaction_id}/tags", response_model=List[TagResponse])
async def get_transaction_tags(
    transaction_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get tags for a transaction"""
    family_id = to_uuid_required(current_user.family_id)
    return await TagService.get_transaction_tags(db, transaction_id, family_id)


@router.put("/transactions/{transaction_id}/tags", response_model=List[TagResponse])
async def set_transaction_tags(
    transaction_id: UUID,
    data: TransactionTagsUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Set tags for a transaction (parent only)"""
    family_id = to_uuid_required(current_user.family_id)
    return await TagService.set_transaction_tags(
        db, transaction_id, family_id, data.tag_ids
    )
