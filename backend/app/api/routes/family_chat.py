"""Family chat routes (W8.1)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ValidationException
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.family_chat_service import FamilyChatService


router = APIRouter()


class ReactionGroup(BaseModel):
    emoji: str
    count: int
    user_ids: List[str] = []


class ChatMessageOut(BaseModel):
    id: UUID
    sender_id: Optional[UUID] = None
    body: str
    created_at: datetime
    reactions: List[ReactionGroup] = []

    model_config = {"from_attributes": True}


class PostMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


class ReactionRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=16)


@router.get("/", response_model=List[ChatMessageOut])
async def list_messages(
    before_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await FamilyChatService.list_messages(
        db,
        to_uuid_required(current_user.family_id),
        limit=limit,
        before_id=before_id,
    )
    reactions = await FamilyChatService.reactions_for_messages(
        db, [r.id for r in rows]
    )
    return [
        ChatMessageOut(
            id=r.id,
            sender_id=r.sender_id,
            body=r.body,
            created_at=r.created_at,
            reactions=[ReactionGroup(**g) for g in reactions.get(r.id, [])],
        )
        for r in rows
    ]


@router.post(
    "/",
    response_model=ChatMessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    data: PostMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        msg = await FamilyChatService.post_message(
            db,
            to_uuid_required(current_user.family_id),
            to_uuid_required(current_user.id),
            data.body,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ChatMessageOut.model_validate(msg)


@router.get("/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    n = await FamilyChatService.unread_count(
        db,
        to_uuid_required(current_user.id),
        to_uuid_required(current_user.family_id),
    )
    return {"unread": n}


@router.post("/mark-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await FamilyChatService.mark_read(db, to_uuid_required(current_user.id))
    return None


async def _reaction_state(db, message_id: UUID, user_id: UUID, emoji: str) -> dict:
    """Authoritative count + membership for one emoji on a message — returned so
    the client can reconcile its optimistic chip to server truth (avoids drift
    when other members reacted concurrently)."""
    groups = (await FamilyChatService.reactions_for_messages(db, [message_id])).get(message_id, [])
    grp = next((g for g in groups if g["emoji"] == emoji), None)
    return {
        "emoji": emoji,
        "count": grp["count"] if grp else 0,
        "mine": bool(grp and str(user_id) in grp["user_ids"]),
    }


@router.post("/{message_id}/reactions")
async def add_reaction(
    message_id: UUID,
    data: ReactionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = to_uuid_required(current_user.id)
    try:
        await FamilyChatService.add_reaction(
            db, message_id, uid, to_uuid_required(current_user.family_id), data.emoji,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _reaction_state(db, message_id, uid, data.emoji)


@router.delete("/{message_id}/reactions")
async def remove_reaction(
    message_id: UUID,
    emoji: str = Query(..., min_length=1, max_length=16),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    uid = to_uuid_required(current_user.id)
    try:
        await FamilyChatService.remove_reaction(
            db, message_id, uid, to_uuid_required(current_user.family_id), emoji,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await _reaction_state(db, message_id, uid, emoji)


@router.get("/stream")
async def stream(
    after_ts: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """SSE poll-stream of new chat messages. Reconnect every ~30s.

    No Depends(get_db): the generator manages its own short-lived sessions so a
    long-lived SSE connection never pins a pooled DB connection.
    """
    gen = FamilyChatService.stream_messages(
        to_uuid_required(current_user.family_id),
        after_ts=after_ts,
    )
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
