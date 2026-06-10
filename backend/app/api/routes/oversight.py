"""Parent oversight: read-only aggregations for the command center."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.oversight import OversightSummary, PendingApprovalItem
from app.services.oversight_service import OversightService

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
