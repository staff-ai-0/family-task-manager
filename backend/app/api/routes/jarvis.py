"""Jarvis copilot routes (W6.1)."""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role, require_teen_or_parent
from app.core.exceptions import ValidationError
from app.core.premium import require_feature
from app.core.rate_limiter import limiter, AI_LIMIT
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.jarvis_service import JarvisService
from app.services.jarvis_pending_action_service import PendingActionService
from app.services.jarvis_mcp_token_service import TokenService


router = APIRouter()


# jctux/platform#86 resolved 2026-07-20: qwen3 (Ollama) confirmed serving 200
# and granted to the FTM key, along with claude-haiku (naming-drift fix — the
# key previously only granted "haiku"). claude-sonnet/gpt-4o stay out — their
# Anthropic/OpenAI upstream fix was never confirmed end-to-end in that issue.
ALLOWED_MODELS = {"gemini-2.5-flash", "qwen3", "claude-haiku"}


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
@limiter.limit(AI_LIMIT)
async def chat(
    request: Request,
    data: ChatRequest,
    current_user: User = Depends(require_teen_or_parent),
    db: AsyncSession = Depends(get_db),
):
    # Plan gate: Jarvis is an LLM feature — free tier has ai_features=False.
    # The per-family JARVIS_DAILY_MESSAGE_CAP inside the service still applies;
    # AI_LIMIT above adds per-IP burst protection on top. Teens get a tool-free,
    # self-scoped coach (see JarvisService); the role drives that branch.
    await require_feature("ai_features", db, current_user)
    model = data.model if data.model in ALLOWED_MODELS else None
    try:
        return await JarvisService.chat(
            db,
            family_id=to_uuid_required(current_user.family_id),
            user_id=to_uuid_required(current_user.id),
            message=data.message,
            model=model,
            preferred_lang=(current_user.preferred_lang or "en"),
            role=current_user.role,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/chat-stream")
@limiter.limit(AI_LIMIT)
async def chat_stream(
    request: Request,
    data: ChatRequest,
    current_user: User = Depends(require_teen_or_parent),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of chat progress. Client consumes via fetch + ReadableStream.

    The stream generator owns its own short-lived session so the long-lived
    SSE body never pins a pooled DB connection. The ``db`` dependency here is
    only used for the pre-stream plan gate and is the SAME cached session the
    auth dependency (require_parent_role → get_current_user) already checked
    out for this request — it adds no extra pool pressure.
    """
    # Plan gate before the stream starts (mirrors /chat).
    await require_feature("ai_features", db, current_user)
    model = data.model if data.model in ALLOWED_MODELS else None
    gen = JarvisService.chat_stream(
        family_id=to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
        message=data.message,
        model=model,
        preferred_lang=(current_user.preferred_lang or "en"),
        role=current_user.role,
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
    current_user: User = Depends(require_teen_or_parent),
    db: AsyncSession = Depends(get_db),
):
    rows = await JarvisService.list_history(
        db,
        to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
        role=current_user.role,
    )
    return [HistoryItem.model_validate(r) for r in rows]


@router.delete("/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(
    current_user: User = Depends(require_teen_or_parent),
    db: AsyncSession = Depends(get_db),
):
    await JarvisService.clear_history(
        db,
        to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
        role=current_user.role,
    )
    return None


# ---------------------------------------------------------------------------
# Pending actions (HITL gate for destructive MCP tool calls)
# ---------------------------------------------------------------------------

class PendingActionResponse(BaseModel):
    id: UUID
    tool_name: str
    params: dict
    summary: str
    status: str
    created_at: datetime
    expires_at: datetime

    model_config = {"from_attributes": True}


@router.get("/actions", response_model=List[PendingActionResponse])
async def list_pending_actions(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Return pending (non-resolved) HITL actions for the authenticated family."""
    rows = await PendingActionService.list_pending(
        db, to_uuid_required(current_user.family_id)
    )
    return [PendingActionResponse.model_validate(r) for r in rows]


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Approve and execute a queued destructive tool call."""
    try:
        result = await PendingActionService.approve(db, action_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return result


@router.post("/actions/{action_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_action(
    action_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Reject (discard without executing) a queued tool call."""
    try:
        await PendingActionService.reject(db, action_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return None


# ---------------------------------------------------------------------------
# MCP bearer token management (list / mint / revoke)
# ---------------------------------------------------------------------------

class McpTokenResponse(BaseModel):
    id: UUID
    label: str
    token_prefix: str
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class McpTokenMintRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=128)


class McpTokenMintResponse(BaseModel):
    token: McpTokenResponse
    secret: str  # one-time plaintext — show once, never again


@router.get("/mcp-tokens", response_model=List[McpTokenResponse])
async def list_mcp_tokens(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """List all MCP bearer tokens for the authenticated family."""
    from sqlalchemy import select
    from app.models.jarvis_mcp_token import JarvisMcpToken

    family_id = to_uuid_required(current_user.family_id)
    result = await db.execute(
        select(JarvisMcpToken)
        .where(JarvisMcpToken.family_id == family_id)
        .order_by(JarvisMcpToken.created_at.desc())
    )
    rows = result.scalars().all()
    return [McpTokenResponse.model_validate(r) for r in rows]


@router.post("/mcp-tokens", response_model=McpTokenMintResponse, status_code=status.HTTP_201_CREATED)
async def mint_mcp_token(
    data: McpTokenMintRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Mint a new per-family MCP bearer token. The plaintext secret is returned once."""
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    row, secret = await TokenService.mint(db, family_id, user_id, data.label)
    return McpTokenMintResponse(
        token=McpTokenResponse.model_validate(row),
        secret=secret,
    )


@router.delete("/mcp-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_mcp_token(
    token_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a MCP bearer token. Silently ignores tokens that don't belong to this family."""
    family_id = to_uuid_required(current_user.family_id)
    await TokenService.revoke(db, token_id, family_id)
    return None
