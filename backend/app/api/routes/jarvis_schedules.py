"""Jarvis schedule routes (W9.1)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.exceptions import NotFoundException, ValidationException
from app.core.premium import require_feature
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.jarvis_schedule_service import JarvisScheduleService


router = APIRouter()


class ScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    prompt: str = Field(..., min_length=1, max_length=2000)
    cron_expr: str = Field(..., min_length=5, max_length=64)
    channel: str = Field("notification", max_length=16)


class ScheduleOut(BaseModel):
    id: UUID
    name: str
    prompt: str
    cron_expr: str
    channel: str
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/", response_model=List[ScheduleOut])
async def list_schedules(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    rows = await JarvisScheduleService.list(
        db, to_uuid_required(current_user.family_id)
    )
    return [ScheduleOut.model_validate(r) for r in rows]


@router.post(
    "/",
    response_model=ScheduleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    data: ScheduleCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    # Schedules fire JarvisService.chat on a cron — same paid gate as /chat.
    await require_feature("ai_features", db, current_user)
    try:
        s = await JarvisScheduleService.create(
            db,
            family_id=to_uuid_required(current_user.family_id),
            created_by=to_uuid_required(current_user.id),
            name=data.name,
            prompt=data.prompt,
            cron_expr=data.cron_expr,
            channel=data.channel,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ScheduleOut.model_validate(s)


@router.post("/{schedule_id}/toggle", response_model=ScheduleOut)
async def toggle(
    schedule_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    try:
        s = await JarvisScheduleService.toggle(
            db, schedule_id, to_uuid_required(current_user.family_id)
        )
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ScheduleOut.model_validate(s)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    try:
        await JarvisScheduleService.delete(
            db, schedule_id, to_uuid_required(current_user.family_id)
        )
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return None
