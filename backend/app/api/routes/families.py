"""
Family management routes

Handles family CRUD operations, member management, and statistics.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, verify_family_id, require_parent_role
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

router = APIRouter()


@router.get("/me", response_model=FamilyWithMembers)
async def get_my_family(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's family with members"""
    family = await FamilyService.get_family(
        db, to_uuid_required(current_user.family_id)
    )
    members = await FamilyService.get_family_members(
        db, to_uuid_required(current_user.family_id)
    )
    return FamilyWithMembers(
        **family.__dict__, members=[UserResponse.model_validate(m) for m in members]
    )


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
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get family by ID"""
    family = await FamilyService.get_family(db, family_id)
    return family


@router.put("/{family_id}", response_model=FamilyResponse)
async def update_family(
    family_data: FamilyUpdate,
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Update family information"""
    family = await FamilyService.update_family(db, family_id, family_data)
    return family


@router.get("/{family_id}/members", response_model=List[UserResponse])
async def get_family_members(
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get all family members"""
    members = await FamilyService.get_family_members(db, family_id)
    return members


@router.get("/{family_id}/stats", response_model=FamilyStats)
async def get_family_stats(
    family_id: UUID = Depends(verify_family_id),
    db: AsyncSession = Depends(get_db),
):
    """Get family statistics"""
    stats = await FamilyService.get_family_stats(db, family_id)
    return stats


# --- Join Code Endpoints ---

@router.post("/join-code/generate")
async def generate_join_code(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Generate or regenerate a family join code (parent only)"""
    family_id = to_uuid_required(current_user.family_id)
    code = await FamilyService.generate_join_code(db, family_id)
    return {"join_code": code}


@router.get("/join-code/current")
async def get_join_code(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Get the current family join code (parent only)"""
    family_id = to_uuid_required(current_user.family_id)
    family = await FamilyService.get_family(db, family_id)
    return {"join_code": family.join_code}
