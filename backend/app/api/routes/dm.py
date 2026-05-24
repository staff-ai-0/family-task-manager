"""Direct message routes (W9.3)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.dm_service import DMService


router = APIRouter()


class ThreadCreate(BaseModel):
    participant_ids: List[UUID] = Field(..., min_length=1)


class ThreadOut(BaseModel):
    id: UUID
    family_id: UUID
    participant_ids: List[UUID]
    updated_at: datetime

    model_config = {"from_attributes": True}


class DMOut(BaseModel):
    id: UUID
    thread_id: UUID
    sender_id: Optional[UUID] = None
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PostDM(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router.get("/threads", response_model=List[ThreadOut])
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await DMService.list_threads_for_user(
        db,
        to_uuid_required(current_user.id),
        to_uuid_required(current_user.family_id),
    )
    return [
        ThreadOut(
            id=t.id,
            family_id=t.family_id,
            participant_ids=[UUID(p) for p in (t.participant_ids or [])],
            updated_at=t.updated_at,
        )
        for t in rows
    ]


@router.post(
    "/threads",
    response_model=ThreadOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_thread(
    data: ThreadCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        t = await DMService.create_thread(
            db,
            to_uuid_required(current_user.family_id),
            to_uuid_required(current_user.id),
            data.participant_ids,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ForbiddenException as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return ThreadOut(
        id=t.id,
        family_id=t.family_id,
        participant_ids=[UUID(p) for p in (t.participant_ids or [])],
        updated_at=t.updated_at,
    )


@router.get("/threads/{thread_id}/stream")
async def stream(
    thread_id: UUID,
    after_ts: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE poll-stream of new DM messages in this thread. Reconnect ~30s."""
    gen = DMService.stream_messages(
        db,
        thread_id,
        to_uuid_required(current_user.id),
        to_uuid_required(current_user.family_id),
        after_ts=after_ts,
    )
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/threads/{thread_id}/messages", response_model=List[DMOut])
async def list_messages(
    thread_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        rows = await DMService.list_messages(
            db,
            thread_id,
            to_uuid_required(current_user.id),
            to_uuid_required(current_user.family_id),
        )
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ForbiddenException as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return [DMOut.model_validate(r) for r in rows]


@router.post(
    "/threads/{thread_id}/messages",
    response_model=DMOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    thread_id: UUID,
    data: PostDM,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        m = await DMService.post_message(
            db,
            thread_id,
            to_uuid_required(current_user.id),
            to_uuid_required(current_user.family_id),
            data.body,
        )
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ForbiddenException as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DMOut.model_validate(m)
