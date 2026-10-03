"""UX-D1 progress (streak + rank, rank-up ack), UX-D2 badges and UX-D3 weekly quest for the signed-in kid."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.models.user import User
from app.schemas.progress import (
    AckBadgesRequest,
    AckQuestRequest,
    AckRankRequest,
    BadgesResponse,
    DeliveryView,
    MysteryBoxView,
    MysteryResponse,
    ProgressResponse,
    QuestResponse,
)
from app.services.badge_service import BadgeService
from app.services.mystery_service import MysteryBoxesOff, MysteryService
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


# ── UX-D4b mystery box ─────────────────────────────────────────────────
@router.get("/mystery", response_model=MysteryResponse)
async def my_mystery(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MysteryResponse:
    """The signed-in kid's boxes. This GET also creates today's box when the
    day is perfect (idempotent) — work on read, like badges and the quest."""
    return await MysteryService.sync(db, current_user)


@router.get("/mystery/deliveries", response_model=List[DeliveryView])
async def deliveries(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> List[DeliveryView]:
    """Surprises revealed by the family's kids that a parent has not handed over yet."""
    return await MysteryService.deliveries(db, current_user.family_id)


@router.post("/mystery/{box_id}/open", response_model=MysteryBoxView)
async def open_box(
    box_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MysteryBoxView:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        return await MysteryService.open(db, current_user, box_id)
    except MysteryBoxesOff:
        raise HTTPException(status_code=409, detail="Mystery boxes are off right now")


@router.post("/mystery/{box_id}/delivered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_delivered(
    box_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await MysteryService.mark_delivered(db, current_user, box_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
