"""Parent oversight: read-only aggregations for the command center, plus the
parent → kid nudge (UX-C2)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.oversight import NudgeResponse, OversightSummary, PendingApprovalItem
from app.services.oversight_service import NudgeRefused, OversightService

router = APIRouter()


@router.get("/summary", response_model=OversightSummary)
async def oversight_summary(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Per-kid summary cards + unified pending counts. Parents only."""
    return await OversightService.get_summary(
        db, to_uuid_required(current_user.family_id)
    )


@router.get("/pending-approvals", response_model=list[PendingApprovalItem])
async def oversight_pending_approvals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Unified approval queue: task assignments + gig claims. Parents only."""
    return await OversightService.get_pending_approvals(
        db, to_uuid_required(current_user.family_id)
    )


@router.post("/nudge/{kid_id}", response_model=NudgeResponse)
async def oversight_nudge(
    kid_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Remind one kid of their open chores. Parents only; 3 h cooldown per kid."""
    try:
        return await OversightService.nudge(
            db, to_uuid_required(current_user.family_id), current_user, kid_id
        )
    except NudgeRefused as refused:
        if refused.reason == "nudge_cooldown":
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "nudge_cooldown",
                    "retry_after_seconds": refused.retry_after_seconds,
                },
                headers={"Retry-After": str(refused.retry_after_seconds)},
            )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="nothing_to_nudge")
