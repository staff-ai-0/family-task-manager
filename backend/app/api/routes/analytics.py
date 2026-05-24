"""Parent analytics routes (W5.2)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.analytics_service import AnalyticsService


router = APIRouter()


@router.get("/pup-score")
async def pup_score(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    return await AnalyticsService.pup_score(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/pup-history")
async def pup_history(
    days: int = 30,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    days = max(7, min(180, int(days)))
    return await AnalyticsService.list_snapshots(
        db, to_uuid_required(current_user.family_id), days=days
    )
