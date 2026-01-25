"""
Reward management routes

Handles reward CRUD operations and redemption.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services import RewardService
from app.schemas.reward import (
    RewardCreate,
    RewardUpdate,
    RewardResponse,
)
from app.schemas.points import PointTransactionResponse
from app.models import User
from app.models.reward import RewardCategory

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
        family_id=to_uuid_required(current_user.family_id),
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
        db, reward_data, family_id=to_uuid_required(current_user.family_id)
    )
    return reward


@router.get("/{reward_id}", response_model=RewardResponse)
async def get_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get reward by ID"""
    reward = await RewardService.get_reward(
        db, reward_id, to_uuid_required(current_user.family_id)
    )
    return reward


@router.post("/{reward_id}/redeem", response_model=PointTransactionResponse)
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a reward with points"""
    transaction = await RewardService.redeem_reward(
        db,
        reward_id=reward_id,
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
    )
    return transaction


@router.put("/{reward_id}", response_model=RewardResponse)
async def update_reward(
    reward_id: UUID,
    reward_data: RewardUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update reward"""
    reward = await RewardService.update_reward(
        db, reward_id, reward_data, to_uuid_required(current_user.family_id)
    )
    return reward


@router.delete("/{reward_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reward(
    reward_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete reward"""
    await RewardService.delete_reward(
        db, reward_id, to_uuid_required(current_user.family_id)
    )
    return None
