"""Family Cup + cooperative boss battle routes (P2).

Family-facing (ANY authenticated member — kids see the boss + cup too, not just
parents): the weekly points leaderboard ("Family Cup") and the cooperative
weekly boss battle derived from assigned task points. Season history is open to
all members; closing a season (persisting its winner) is parent-only.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.family_cup_service import FamilyCupService


router = APIRouter()


@router.get("/")
async def family_cup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current week's Family Cup leaderboard + cooperative boss battle."""
    return await FamilyCupService.summary(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/history")
async def family_cup_history(
    limit: int = Query(12, ge=1, le=52),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Past season winners (most recent first)."""
    return await FamilyCupService.list_past_seasons(
        db, to_uuid_required(current_user.family_id), limit=limit
    )


@router.post("/close-season")
async def close_season(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Finalize LAST week's Family Cup season, persisting its winner. Parent
    only. Idempotent — safe to call more than once (refreshes the stored
    winner). Intended to be triggered weekly (Monday) by a parent or a cron."""
    return await FamilyCupService.close_previous_season(
        db, to_uuid_required(current_user.family_id)
    )
