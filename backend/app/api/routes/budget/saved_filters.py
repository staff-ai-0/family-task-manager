"""
Saved Filter routes

CRUD endpoints for saved transaction filter presets.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.saved_filter_service import SavedFilterService
from app.schemas.budget import (
    SavedFilterCreate,
    SavedFilterUpdate,
    SavedFilterResponse,
)
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[SavedFilterResponse])
async def list_saved_filters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all saved filters for the family"""
    family_id = to_uuid_required(current_user.family_id)
    return await SavedFilterService.list_by_family(db, family_id)


@router.post("/", response_model=SavedFilterResponse, status_code=status.HTTP_201_CREATED)
async def create_saved_filter(
    data: SavedFilterCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new saved filter (parent only)"""
    return await SavedFilterService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
        data=data,
    )


@router.get("/{filter_id}", response_model=SavedFilterResponse)
async def get_saved_filter(
    filter_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a saved filter by ID"""
    return await SavedFilterService.get_by_id(
        db, filter_id, to_uuid_required(current_user.family_id)
    )


@router.put("/{filter_id}", response_model=SavedFilterResponse)
async def update_saved_filter(
    filter_id: UUID,
    data: SavedFilterUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a saved filter (parent only)"""
    return await SavedFilterService.update(
        db, filter_id, to_uuid_required(current_user.family_id), data
    )


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_filter(
    filter_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved filter (parent only)"""
    await SavedFilterService.delete_by_id(
        db, filter_id, to_uuid_required(current_user.family_id)
    )
    return None
