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
from app.core.exceptions import ForbiddenException
from app.core.type_utils import to_uuid_required
from app.models.user import UserRole
from app.services import RewardService
from app.schemas.reward import (
    RewardCreate,
    RewardUpdate,
    RewardResponse,
    RewardRedemptionResponse,
    RedeemResult,
    RedemptionDecision,
)
from app.schemas.points import PointTransactionResponse
from app.schemas.reward_goal import GoalSet, GoalProgress
from app.services.reward_goal_service import RewardGoalService
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


@router.get("/goal", response_model=Optional[GoalProgress])
async def get_reward_goal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current kid/teen's active goal with live progress. Returns null for parents."""
    if current_user.role == UserRole.PARENT:
        return None
    return await RewardGoalService.get_active_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )


@router.put("/goal", response_model=GoalProgress)
async def set_reward_goal(
    data: GoalSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set active reward goal. CHILD/TEEN only."""
    if current_user.role == UserRole.PARENT:
        raise ForbiddenException("Parents cannot set a reward goal")
    await RewardGoalService.set_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        reward_id=data.reward_id,
        db=db,
    )
    return await RewardGoalService.get_active_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )


@router.delete("/goal", status_code=status.HTTP_204_NO_CONTENT)
async def clear_reward_goal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear active reward goal."""
    if current_user.role == UserRole.PARENT:
        raise ForbiddenException("Parents cannot clear a reward goal")
    await RewardGoalService.clear_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )
    return None


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


@router.post("/{reward_id}/redeem", response_model=None)
async def redeem_reward(
    reward_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Redeem a reward with points.

    Backward-compatible: the immediate (non-approval) path returns the same
    PointTransaction shape as before, so existing strict-decoding mobile
    clients keep working. Approval-gated rewards instead return a RedeemResult
    with status="pending" (queued, no deduction yet).
    """
    result = await RewardService.redeem_reward(
        db,
        reward_id=reward_id,
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
    )
    if result.get("status") == "completed" and result.get("transaction") is not None:
        # Unchanged legacy contract for the common path.
        return PointTransactionResponse.model_validate(result["transaction"])
    return RedeemResult(
        status=result["status"],
        message=result["message"],
        points_spent=result.get("points_spent", 0),
        new_balance=result.get("new_balance"),
        redemption_id=result.get("redemption_id"),
    )


# ── Parent-approval reward queue ──────────────────────────────────────────

@router.get("/redemptions/pending", response_model=List[RewardRedemptionResponse])
async def list_pending_redemptions(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Reward redemptions awaiting a parent decision (parent only)."""
    return await RewardService.list_pending_redemptions(
        db, to_uuid_required(current_user.family_id)
    )


@router.post("/redemptions/{redemption_id}/approve", response_model=RewardRedemptionResponse)
async def approve_redemption(
    redemption_id: UUID,
    decision: RedemptionDecision | None = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Approve a queued redemption — deducts the points now (parent only)."""
    return await RewardService.decide_redemption(
        db, redemption_id=redemption_id,
        family_id=to_uuid_required(current_user.family_id),
        parent_id=to_uuid_required(current_user.id),
        approve=True,
        notes=(decision.notes if decision else None),
    )


@router.post("/redemptions/{redemption_id}/reject", response_model=RewardRedemptionResponse)
async def reject_redemption(
    redemption_id: UUID,
    decision: RedemptionDecision | None = None,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Reject a queued redemption — no points deducted (parent only)."""
    return await RewardService.decide_redemption(
        db, redemption_id=redemption_id,
        family_id=to_uuid_required(current_user.family_id),
        parent_id=to_uuid_required(current_user.id),
        approve=False,
        notes=(decision.notes if decision else None),
    )


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
