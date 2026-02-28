"""
Category routes

CRUD endpoints for budget category groups and categories.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryGroupUpdate,
    CategoryGroupResponse,
    CategoryGroupWithCategories,
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
)
from app.models import User

router = APIRouter()


# ============================================================================
# CATEGORY GROUP ENDPOINTS
# ============================================================================

@router.get("/groups", response_model=List[CategoryGroupWithCategories])
async def list_category_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    include_hidden: bool = Query(False, description="Include hidden groups/categories"),
):
    """List all category groups with their categories"""
    groups = await CategoryGroupService.list_with_categories(
        db,
        family_id=to_uuid_required(current_user.family_id),
        include_hidden=include_hidden,
    )
    return groups


@router.post("/groups", response_model=CategoryGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_category_group(
    data: CategoryGroupCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new category group (parent only)"""
    group = await CategoryGroupService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return group


@router.get("/groups/{group_id}", response_model=CategoryGroupResponse)
async def get_category_group(
    group_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a category group by ID"""
    group = await CategoryGroupService.get_by_id(
        db,
        group_id,
        to_uuid_required(current_user.family_id),
    )
    return group


@router.put("/groups/{group_id}", response_model=CategoryGroupResponse)
async def update_category_group(
    group_id: UUID,
    data: CategoryGroupUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a category group (parent only)"""
    group = await CategoryGroupService.update(
        db,
        group_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return group


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category_group(
    group_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a category group (parent only)"""
    await CategoryGroupService.delete_by_id(
        db,
        group_id,
        to_uuid_required(current_user.family_id),
    )


# ============================================================================
# CATEGORY ENDPOINTS
# ============================================================================

@router.get("/", response_model=List[CategoryResponse])
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    group_id: UUID = Query(None, description="Filter by group ID"),
    include_hidden: bool = Query(False, description="Include hidden categories"),
):
    """List all categories, optionally filtered by group"""
    if group_id:
        categories = await CategoryService.list_by_group(
            db,
            group_id,
            to_uuid_required(current_user.family_id),
            include_hidden=include_hidden,
        )
    else:
        categories = await CategoryService.list_by_family(
            db,
            to_uuid_required(current_user.family_id),
        )
        if not include_hidden:
            categories = [c for c in categories if not c.hidden]
    
    return categories


@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    data: CategoryCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new category (parent only)"""
    category = await CategoryService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return category


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a category by ID"""
    category = await CategoryService.get_by_id(
        db,
        category_id,
        to_uuid_required(current_user.family_id),
    )
    return category


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: UUID,
    data: CategoryUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a category (parent only)"""
    category = await CategoryService.update(
        db,
        category_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a category (parent only)"""
    await CategoryService.delete_by_id(
        db,
        category_id,
        to_uuid_required(current_user.family_id),
    )
