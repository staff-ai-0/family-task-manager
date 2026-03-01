"""
Budget Goal routes

CRUD endpoints for budget goals and spending targets.
"""

from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from datetime import date

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.budget.goal_service import GoalService
from app.schemas.budget import (
    GoalCreate,
    GoalUpdate,
    GoalResponse,
    GoalProgress,
)
from app.models import User

router = APIRouter()


@router.get("/", response_model=List[GoalResponse])
async def list_goals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    category_id: Optional[UUID] = Query(None, description="Filter by category ID"),
    active_only: bool = Query(True, description="Only return active goals"),
):
    """List budget goals for the family"""
    family_id = to_uuid_required(current_user.family_id)
    
    if category_id:
        goals = await GoalService.list_by_category(
            db, category_id, family_id, active_only=active_only
        )
    else:
        goals = await GoalService.list_active(
            db, family_id
        ) if active_only else await GoalService.list_by_family(db, family_id)
    
    return goals


@router.post("/", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    data: GoalCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a new budget goal (parent only)"""
    goal = await GoalService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        data=data,
    )
    return goal


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific budget goal"""
    goal = await GoalService.get_by_id(
        db, goal_id, to_uuid_required(current_user.family_id)
    )
    return goal


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: UUID,
    data: GoalUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Update a budget goal (parent only)"""
    goal = await GoalService.update(
        db,
        goal_id,
        to_uuid_required(current_user.family_id),
        data,
    )
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Delete a budget goal (parent only)"""
    await GoalService.delete_by_id(
        db, goal_id, to_uuid_required(current_user.family_id)
    )
    return None


@router.get("/{goal_id}/progress", response_model=GoalProgress)
async def get_goal_progress(
    goal_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get progress towards a specific goal"""
    progress = await GoalService.calculate_progress(
        db, goal_id, to_uuid_required(current_user.family_id)
    )
    return progress
