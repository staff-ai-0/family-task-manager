"""
User management routes

Handles user profile operations and points management.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role, get_family_user
from app.services import AuthService, PointsService
from app.schemas.user import UserUpdate, UserResponse
from app.schemas.points import (
    PointsSummary,
    PointTransactionResponse,
    ParentAdjustment,
)
from app.models import User

router = APIRouter()


@router.get("/me/points", response_model=PointsSummary)
async def get_my_points_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get my points summary"""
    summary = await PointsService.get_points_summary(db, current_user.id)
    return summary


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user: User = Depends(get_family_user),
):
    """Get user by ID (must be in same family)"""
    return user


@router.get("/{user_id}/points", response_model=PointsSummary)
async def get_user_points_summary(
    user: User = Depends(get_family_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user points summary (must be in same family)"""
    summary = await PointsService.get_points_summary(db, user.id)
    return summary


@router.post("/points/adjust", response_model=PointTransactionResponse)
async def adjust_user_points(
    adjustment: ParentAdjustment,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Manually adjust user points (parent only)"""
    transaction = await PointsService.create_parent_adjustment(
        db,
        adjustment,
        parent_id=current_user.id,
        family_id=current_user.family_id,
    )
    return transaction


@router.put("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user: User = Depends(get_family_user),
    _: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account (parent only)"""
    user = await AuthService.deactivate_user(db, user.id)
    return user


@router.put("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user: User = Depends(get_family_user),
    _: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Activate a user account (parent only)"""
    user = await AuthService.activate_user(db, user.id)
    return user
