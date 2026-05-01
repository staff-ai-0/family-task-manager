"""
Payee routes

CRUD endpoints for budget payees.
"""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.payee_service import PayeeService
from app.schemas.budget import PayeeCreate, PayeeUpdate, PayeeMergeRequest, PayeeResponse
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[PayeeResponse])
async def list_payees(
    favorites_only: bool = Query(False, description="Only return favorite payees"),
    limit: int = Query(500, ge=1, le=2000, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all payees, optionally filtered to favorites only"""
    payees = await PayeeService.list_by_family_filtered(
        db,
        to_uuid_required(current_user.family_id),
        favorites_only=favorites_only,
        limit=limit,
        offset=offset,
    )
    return payees


@router.post("/", response_model=PayeeResponse, status_code=status.HTTP_201_CREATED)
async def create_payee(
    data: PayeeCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new payee (parent only)"""
    payee = await PayeeService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return payee


@router.post("/merge", response_model=PayeeResponse)
async def merge_payees(
    data: PayeeMergeRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Merge source payees into target payee (parent only)"""
    payee = await PayeeService.merge(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return payee


@router.get("/{payee_id}", response_model=PayeeResponse)
async def get_payee(
    payee_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a payee by ID"""
    payee = await PayeeService.get_by_id(
        db,
        payee_id,
        to_uuid_required(current_user.family_id),
    )
    return payee


@router.put("/{payee_id}", response_model=PayeeResponse)
async def update_payee(
    payee_id: UUID,
    data: PayeeUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a payee (parent only)"""
    payee = await PayeeService.update(
        db,
        payee_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return payee


@router.delete("/{payee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_payee(
    payee_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a payee (parent only)"""
    await PayeeService.delete_by_id(
        db,
        payee_id,
        to_uuid_required(current_user.family_id),
    )
