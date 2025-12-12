"""
Consequence management routes

Handles consequence CRUD operations and resolution.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.services import ConsequenceService
from app.schemas.consequence import (
    ConsequenceCreate,
    ConsequenceUpdate,
    ConsequenceResponse,
)
from app.models import User
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
)

router = APIRouter()


@router.get("/", response_model=List[ConsequenceResponse])
async def list_consequences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None, description="Filter by user"),
    active_only: bool = Query(False, description="Show only active consequences"),
):
    """List active consequences"""
    consequences = await ConsequenceService.list_consequences(
        db,
        family_id=current_user.family_id,
        user_id=user_id,
        active_only=active_only,
    )
    return consequences


@router.get("/me/active", response_model=List[ConsequenceResponse])
async def get_my_active_consequences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get my active consequences"""
    consequences = await ConsequenceService.get_active_consequences(db, current_user.id)
    return consequences


@router.post("/", response_model=ConsequenceResponse, status_code=status.HTTP_201_CREATED)
async def create_consequence(
    consequence_data: ConsequenceCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new consequence (parent only)"""
    try:
        consequence = await ConsequenceService.create_consequence(
            db, consequence_data, family_id=current_user.family_id
        )
        return consequence
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{consequence_id}/resolve", response_model=ConsequenceResponse)
async def resolve_consequence(
    consequence_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a consequence (parent only)"""
    try:
        consequence = await ConsequenceService.resolve_consequence(
            db, consequence_id, current_user.family_id
        )
        return consequence
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{consequence_id}", response_model=ConsequenceResponse)
async def update_consequence(
    consequence_id: UUID,
    consequence_data: ConsequenceUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update consequence"""
    try:
        consequence = await ConsequenceService.update_consequence(
            db, consequence_id, consequence_data, current_user.family_id
        )
        return consequence
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{consequence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_consequence(
    consequence_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete consequence"""
    try:
        await ConsequenceService.delete_consequence(
            db, consequence_id, current_user.family_id
        )
        return None
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/check-expired", response_model=List[ConsequenceResponse])
async def check_expired_consequences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check for expired consequences and auto-resolve"""
    consequences = await ConsequenceService.check_expired_consequences(
        db, current_user.family_id
    )
    return consequences

