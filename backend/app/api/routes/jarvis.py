"""Jarvis copilot routes (W6.1)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.exceptions import ValidationError
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.jarvis_service import JarvisService


router = APIRouter()


# Only models the FTM LiteLLM virtual key is granted (see jctux/platform#86).
# qwen3 + claude-haiku were offered but the key grants qwen2.5 + haiku, so
# selecting them returned 401 key_model_access_denied. Re-add qwen3 here once
# platform grants the key access to it.
ALLOWED_MODELS = {"haiku", "claude-sonnet", "gpt-4o", "gemini-2.5-flash"}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    model: Optional[str] = Field(None, description="LiteLLM model alias override")


class ChatReply(BaseModel):
    reply: str
    message_id: str
    actions: List[str] = []


class HistoryItem(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post("/chat", response_model=ChatReply)
async def chat(
    data: ChatRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    model = data.model if data.model in ALLOWED_MODELS else None
    try:
        return await JarvisService.chat(
            db,
            family_id=to_uuid_required(current_user.family_id),
            user_id=to_uuid_required(current_user.id),
            message=data.message,
            model=model,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/chat-stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of chat progress. Client consumes via fetch + ReadableStream."""
    model = data.model if data.model in ALLOWED_MODELS else None
    gen = JarvisService.chat_stream(
        db,
        family_id=to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
        message=data.message,
        model=model,
    )
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", response_model=List[HistoryItem])
async def history(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    rows = await JarvisService.list_history(
        db, to_uuid_required(current_user.family_id)
    )
    return [HistoryItem.model_validate(r) for r in rows]


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await JarvisService.clear_history(
        db, to_uuid_required(current_user.family_id)
    )
    return None
