"""Operator write actions. Every route audits."""

from datetime import date
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


class GrantCreditRequest(ReasonRequest):
    tier: str = Field(..., pattern=r"^(plus|pro)$")
    # None => lifetime. Bounded at 5 years so a typo cannot comp a family
    # for a century by accident; use days=null for a deliberate lifetime.
    days: Optional[int] = Field(None, ge=1, le=1825)


class SuspendRequest(ReasonRequest):
    suspended: bool


class ModulesRequest(ReasonRequest):
    # None restores the default registry, which means ALL modules on.
    enabled_modules: Optional[list[str]] = None


class ActiveRequest(ReasonRequest):
    active: bool


class CancelDeletionRequest(ReasonRequest):
    pass


class ReleasePaycheckRequest(ReasonRequest):
    kid_id: UUID
    week_of: date


class RestoreRequest(ReasonRequest):
    item_type: str
    item_id: UUID


@router.post("/families/{family_id}/comp-plus")
async def comp_plus(
    family_id: UUID,
    body: CompPlusRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant free Plus for N days. Thin alias over the general credit grant,
    kept so the existing operator UI keeps working."""
    return await AdminActionService.grant_plan_credit(
        db,
        operator=operator,
        family_id=family_id,
        tier="plus",
        days=body.days,
        reason=body.reason,
    )


@router.post("/families/{family_id}/credits")
async def grant_credit(
    family_id: UUID,
    body: GrantCreditRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant free time at any tier. days=null grants it for life."""
    return await AdminActionService.grant_plan_credit(
        db,
        operator=operator,
        family_id=family_id,
        tier=body.tier,
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


@router.post("/families/{family_id}/cancel-deletion")
async def cancel_deletion(
    family_id: UUID,
    body: CancelDeletionRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reinstate a family inside its 30-day recovery window.

    Billing is NOT restored — the PayPal subscription was cancelled at
    soft-delete time and the family must re-subscribe.
    """
    return await AdminActionService.cancel_deletion(
        db, operator=operator, family_id=family_id, reason=body.reason
    )


@router.post("/families/{family_id}/release-paycheck")
async def release_paycheck(
    family_id: UUID,
    body: ReleasePaycheckRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force-release a stuck chore paycheck. Idempotent per (kid, week)."""
    return await AdminActionService.release_paycheck(
        db,
        operator=operator,
        family_id=family_id,
        kid_id=body.kid_id,
        week_of=body.week_of,
        reason=body.reason,
    )


@router.post("/families/{family_id}/assignments/{assignment_id}/undo-approval")
async def undo_approval(
    family_id: UUID,
    assignment_id: UUID,
    body: ReasonRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revert a mistakenly-approved chore. Refuses bonus and gig reversals."""
    return await AdminActionService.undo_chore_approval(
        db,
        operator=operator,
        family_id=family_id,
        assignment_id=assignment_id,
        reason=body.reason,
    )


@router.post("/families/{family_id}/restore")
async def restore_recycled(
    family_id: UUID,
    body: RestoreRequest,
    operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Restore one budget row from the family's recycle bin."""
    return await AdminActionService.restore_recycled(
        db,
        operator=operator,
        family_id=family_id,
        item_type=body.item_type,
        item_id=body.item_id,
        reason=body.reason,
    )
