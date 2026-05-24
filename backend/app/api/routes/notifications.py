"""Notification routes (W3.2)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.notification_service import NotificationService


router = APIRouter()


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: Optional[str] = None
    link: Optional[str] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    unread: int
    items: List[NotificationOut]


@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    only_unread: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    rows = await NotificationService.list_for_user(
        db, user_id, family_id, only_unread=only_unread, limit=limit
    )
    unread = await NotificationService.unread_count(db, user_id, family_id)
    return NotificationListResponse(
        unread=unread,
        items=[NotificationOut.model_validate(n) for n in rows],
    )


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    n = await NotificationService.unread_count(db, user_id, family_id)
    return {"unread": n}


@router.post("/{notif_id}/read", response_model=NotificationOut)
async def mark_read(
    notif_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    n = await NotificationService.mark_read(
        db,
        notif_id,
        to_uuid_required(current_user.id),
        to_uuid_required(current_user.family_id),
    )
    return NotificationOut.model_validate(n)


@router.post("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await NotificationService.mark_all_read(
        db,
        to_uuid_required(current_user.id),
        to_uuid_required(current_user.family_id),
    )
    return {"marked": count}
