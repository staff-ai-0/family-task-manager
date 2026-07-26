"""Platform-wide operator reads."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_read_service import AdminReadService

router = APIRouter()


@router.get("/overview")
async def platform_overview(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-screen platform state: tenants, users, billing, queues."""
    return await AdminReadService.platform_pulse(db)


@router.get("/billing-review")
async def billing_review(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Subscriptions flagged for human review by the PayPal webhook."""
    return await AdminReadService.billing_review_queue(db)


@router.get("/deletions")
async def pending_deletions(
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Families inside the recovery window."""
    return await AdminReadService.pending_purge_queue(db)


@router.get("/audit")
async def audit_log(
    family_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Operator audit trail."""
    return await AdminReadService.audit_log(
        db, family_id=family_id, action=action, limit=limit, offset=offset
    )
