"""Operator write actions. Every route audits."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_superadmin
from app.models.user import User
from app.services.admin.admin_action_service import AdminActionService

router = APIRouter()


class ReasonRequest(BaseModel):
    """Every operator action carries an operator-written reason."""

    reason: str = Field(..., min_length=3, max_length=500)


class CompPlusRequest(ReasonRequest):
    days: int = Field(30, ge=1, le=365)


class SuspendRequest(ReasonRequest):
    suspended: bool


class ModulesRequest(ReasonRequest):
    # None restores the default registry, which means ALL modules on.
    enabled_modules: Optional[list[str]] = None


class ActiveRequest(ReasonRequest):
    active: bool


@router.post("/families/{family_id}/comp-plus")
async def comp_plus(
    family_id: UUID,
    body: CompPlusRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant free Plus until now + days (absolute, not stacked)."""
    return await AdminActionService.comp_plus_month(
        db,
        operator=operator,
        family_id=family_id,
        days=body.days,
        reason=body.reason,
    )


@router.post("/families/{family_id}/suspend")
async def suspend_family(
    family_id: UUID,
    body: SuspendRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lock a family out of the app, or reinstate it."""
    return await AdminActionService.set_family_active(
        db,
        operator=operator,
        family_id=family_id,
        suspended=body.suspended,
        reason=body.reason,
    )


@router.post("/families/{family_id}/modules")
async def set_modules(
    family_id: UUID,
    body: ModulesRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rewrite the family's module registry."""
    return await AdminActionService.set_modules(
        db,
        operator=operator,
        family_id=family_id,
        enabled_modules=body.enabled_modules,
        reason=body.reason,
    )


@router.post("/users/{user_id}/active")
async def set_user_active(
    user_id: UUID,
    body: ActiveRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Deactivate or reactivate one member."""
    return await AdminActionService.set_user_active(
        db,
        operator=operator,
        user_id=user_id,
        active=body.active,
        reason=body.reason,
    )


@router.post("/users/{user_id}/resend-verification")
async def resend_verification(
    user_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a fresh verification link."""
    return await AdminActionService.resend_verification(
        db, operator=operator, user_id=user_id, reason=body.reason
    )


@router.post("/users/{user_id}/password-reset")
async def password_reset(
    user_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a reset link and invalidate outstanding sessions."""
    return await AdminActionService.trigger_password_reset(
        db, operator=operator, user_id=user_id, reason=body.reason
    )
