"""
Family management routes

Handles family CRUD operations, member management, and statistics.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.services import FamilyService
from app.schemas.family import (
    FamilyCreate,
    FamilyUpdate,
    FamilyResponse,
    FamilyWithMembers,
    FamilyStats,
)
from app.schemas.user import UserResponse
from app.models import User
from app.core.exceptions import NotFoundException

router = APIRouter()


@router.get("/me", response_model=FamilyWithMembers)
async def get_my_family(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's family with members"""
    try:
        family = await FamilyService.get_family(
            db, to_uuid_required(current_user.family_id)
        )
        members = await FamilyService.get_family_members(
            db, to_uuid_required(current_user.family_id)
        )
        return FamilyWithMembers(
            **family.__dict__, members=[UserResponse.model_validate(m) for m in members]
        )
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/", response_model=FamilyResponse, status_code=status.HTTP_201_CREATED)
async def create_family(
    family_data: FamilyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new family"""
    family = await FamilyService.create_family(
        db, family_data, to_uuid_required(current_user.id)
    )
    return family


@router.get("/{family_id}", response_model=FamilyResponse)
async def get_family(
    family_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get family by ID"""
    if to_uuid_required(current_user.family_id) != family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own family",
        )
    try:
        family = await FamilyService.get_family(db, family_id)
        return family
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("/{family_id}", response_model=FamilyResponse)
async def update_family(
    family_id: UUID,
    family_data: FamilyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update family information"""
    if to_uuid_required(current_user.family_id) != family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own family",
        )
    try:
        family = await FamilyService.update_family(db, family_id, family_data)
        return family
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{family_id}/members", response_model=List[UserResponse])
async def get_family_members(
    family_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all family members"""
    if to_uuid_required(current_user.family_id) != family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own family members",
        )
    members = await FamilyService.get_family_members(db, family_id)
    return members


@router.get("/{family_id}/stats", response_model=FamilyStats)
async def get_family_stats(
    family_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get family statistics"""
    if to_uuid_required(current_user.family_id) != family_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own family stats",
        )
    stats = await FamilyService.get_family_stats(db, family_id)
    return stats
