"""
Reward management routes

Handles reward CRUD operations and redemption.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.services import RewardService
from app.schemas.reward import (
    RewardCreate,
    RewardUpdate,
    RewardResponse,
)
from app.schemas.points import PointTransactionResponse
from app.models import User
from app.models.reward import RewardCategory
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    ForbiddenException,
)

router = APIRouter()


@router.get("/", response_model=List[RewardResponse])
async def list_rewards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    category: Optional[RewardCategory] = Query(None, description="Filter by category"),
    is_active: Optional[bool] = Query(True, description="Filter by active status"),
):
    """List all rewards"""
    rewards = await RewardService.list_rewards(
        db,
        family_id=current_user.family_id,
        category=category,
        is_active=is_active,
    )
    return rewards


@router.post("/", response_model=RewardResponse, status_code=status.HTTP_201_CREATED)
async def create_reward(
    reward_data: RewardCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new reward (parent only)"""
    reward = await RewardService.create_reward(
        db, reward_data, family_id=current_user.family_id
    )
    return reward


@router.get("/{reward_id}", response_model=RewardResponse)
async def get_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get reward by ID"""
    try:
        reward = await RewardService.get_reward(db, reward_id, current_user.family_id)
        return reward
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{reward_id}/redeem", response_model=PointTransactionResponse)
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a reward with points"""
    try:
        transaction = await RewardService.redeem_reward(
            db,
            reward_id=reward_id,
            user_id=current_user.id,
            family_id=current_user.family_id,
        )
        return transaction
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.put("/{reward_id}", response_model=RewardResponse)
async def update_reward(
    reward_id: UUID,
    reward_data: RewardUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update reward"""
    try:
        reward = await RewardService.update_reward(
            db, reward_id, reward_data, current_user.family_id
        )
        return reward
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{reward_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reward(
    reward_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete reward"""
    try:
        await RewardService.delete_reward(db, reward_id, current_user.family_id)
        return None
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

