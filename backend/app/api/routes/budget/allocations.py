"""
Allocation routes

CRUD endpoints for budget allocations.
"""

from fastapi import APIRouter, Depends, status, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.allocation_service import AllocationService
from app.schemas.budget import AllocationCreate, AllocationUpdate, AllocationResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[AllocationResponse])
async def list_allocations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    month: date = Query(None, description="Filter by month (first day)"),
    category_id: UUID = Query(None, description="Filter by category ID"),
):
    """List allocations with optional filters"""
    family_id = to_uuid_required(current_user.family_id)
    
    if month:
        allocations = await AllocationService.list_by_month(db, family_id, month)
    elif category_id:
        allocations = await AllocationService.list_by_category(db, category_id, family_id)
    else:
        allocations = await AllocationService.list_by_family(db, family_id)
    
    return allocations


@router.post("/", response_model=AllocationResponse, status_code=status.HTTP_201_CREATED)
async def create_allocation(
    data: AllocationCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new budget allocation (parent only)"""
    allocation = await AllocationService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return allocation


@router.get("/{allocation_id}", response_model=AllocationResponse)
async def get_allocation(
    allocation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get an allocation by ID"""
    allocation = await AllocationService.get_by_id(
        db,
        allocation_id,
        to_uuid_required(current_user.family_id),
    )
    return allocation


@router.put("/{allocation_id}", response_model=AllocationResponse)
async def update_allocation(
    allocation_id: UUID,
    data: AllocationUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update an allocation (parent only)"""
    allocation = await AllocationService.update(
        db,
        allocation_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return allocation


@router.delete("/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_allocation(
    allocation_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete an allocation (parent only)"""
    await AllocationService.delete_by_id(
        db,
        allocation_id,
        to_uuid_required(current_user.family_id),
    )


@router.post("/set", response_model=AllocationResponse)
async def set_category_budget(
    category_id: UUID = Body(...),
    month: date = Body(...),
    amount: int = Body(..., description="Amount in cents"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Set budget amount for a category in a specific month (creates or updates)"""
    allocation = await AllocationService.set_category_budget(
        db,
        family_id=to_uuid_required(current_user.family_id),
        category_id=category_id,
        month=month,
        amount=amount,
    )
    return allocation
