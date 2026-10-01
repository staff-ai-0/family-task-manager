"""UX-D1 progress (streak + rank, rank-up ack), UX-D2 badges and UX-D3 weekly quest for the signed-in kid."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.progress import (
    AckBadgesRequest,
    AckQuestRequest,
    AckRankRequest,
    BadgesResponse,
    ProgressResponse,
    QuestResponse,
)
from app.services.badge_service import BadgeService
from app.services.progress_service import KID_ROLES, ProgressService
from app.services.quest_service import QuestService

router = APIRouter()


@router.get("/me", response_model=ProgressResponse)
async def my_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    return await ProgressService.progress_for(db, current_user)


@router.post("/me/ack-rank", status_code=status.HTTP_204_NO_CONTENT)
async def ack_rank(
    data: AckRankRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    await ProgressService.ack_rank(db, current_user, data.rank)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/badges", response_model=BadgesResponse)
async def my_badges(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BadgesResponse:
    """Badge progress for the signed-in kid. This GET also records any newly
    earned tier (idempotent insert-if-missing) — awarding lives here, on read,
    instead of in hooks across every service that can move a count."""
    return await BadgeService.sync(db, current_user)


@router.post("/badges/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_badges(
    data: AckBadgesRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    await BadgeService.ack(db, current_user, data.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/quest", response_model=QuestResponse)
async def my_quest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    """The signed-in kid's weekly quest. This GET also creates the week's
    quest and pays the bonus once the goal is reached (both idempotent) —
    like badges, the work happens on read instead of in hooks elsewhere."""
    return await QuestService.sync(db, current_user)


@router.post("/quest/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_quest(
    data: AckQuestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    await QuestService.ack(db, current_user, data.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
