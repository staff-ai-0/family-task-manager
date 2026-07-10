"""
User management routes

Handles user profile operations and points management.
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role, get_family_user
from app.services import AuthService, PointsService
from app.schemas.user import UserUpdate, UserResponse
from app.schemas.points import (
    PointsSummary,
    PointTransactionResponse,
    ParentAdjustment,
    QuickPointsAdjustment,
)
from app.models import User
from app.models.user import UserRole

router = APIRouter()


@router.get("/me/points", response_model=PointsSummary)
async def get_my_points_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get my points summary"""
    summary = await PointsService.get_points_summary(db, current_user.id)
    return summary


@router.get("/me/points/history", response_model=List[PointTransactionResponse])
async def get_my_points_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """My point transaction ledger (earned, spent, adjustments) — newest first.

    Gives kids a visible answer to "why did my balance change?"; the reason a
    parent types on an adjustment is stored in `description`.
    """
    return await PointsService.get_transaction_history(
        db, current_user.id, limit=min(max(limit, 1), 200)
    )


@router.get("/colors")
async def get_member_colors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-member display colors for the caller's family (P1-KIOSK).

    Any member may read (colors show on chat/calendar/task lists for
    everyone). Resolution = parent-set override (Redis) or deterministic
    brand-palette fallback. Registered BEFORE /{user_id} so the literal
    path wins over the UUID param route.
    """
    from sqlalchemy import and_ as sa_and, select as sa_select

    from app.services.member_prefs_service import (
        MemberPrefsService,
        color_hex,
        resolve_color_name,
    )

    # Active members only — matches the kiosk /member-prefs listing so
    # deactivated members never leak into client color maps.
    q = sa_select(User).where(
        sa_and(
            User.family_id == current_user.family_id,
            User.is_active.is_(True),
        )
    )
    users = list((await db.execute(q)).scalars().all())
    prefs = await MemberPrefsService.get_family_prefs(current_user.family_id)
    return [
        {
            "user_id": str(u.id),
            "name": u.name,
            "color": color_hex(
                resolve_color_name(u.id, prefs.get(str(u.id)))
            ),
        }
        for u in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user: User = Depends(get_family_user),
):
    """Get user by ID (must be in same family)"""
    return user


@router.get("/{user_id}/points", response_model=PointsSummary)
async def get_user_points_summary(
    user: User = Depends(get_family_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user points summary (must be in same family)"""
    summary = await PointsService.get_points_summary(db, user.id)
    return summary


@router.post("/points/adjust", response_model=PointTransactionResponse)
async def adjust_user_points(
    adjustment: ParentAdjustment,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Manually adjust user points (parent only)"""
    transaction = await PointsService.create_parent_adjustment(
        db,
        adjustment,
        parent_id=current_user.id,
        family_id=current_user.family_id,
    )
    return transaction


@router.post("/points/quick-adjust", response_model=PointTransactionResponse)
async def quick_adjust_points(
    adjustment: QuickPointsAdjustment,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """1-tap parent award/deduct (W4.5).

    Same ledger as /points/adjust (PARENT_ADJUSTMENT transaction with the
    reason in `description`), but the reason is optional — a localized
    default is filled in — and the kid gets an in-app notification so the
    balance change is never silent.
    """
    from app.services.base_service import get_user_by_id
    from app.core.exceptions import ForbiddenException

    target = await get_user_by_id(db, adjustment.user_id)
    # Quick-adjust is a kid affordance: the dashboard hides the chips on
    # parent rows, so the API must match — no adjusting another parent's
    # (or your own) balance through this shortcut. The full /points/adjust
    # ledger flow is unchanged.
    if target.role == UserRole.PARENT:
        raise ForbiddenException(
            "Quick adjust only targets kids — parent balances cannot be "
            "adjusted here"
        )
    kid_lang = getattr(target, "preferred_lang", None) or "es"
    reason = (adjustment.reason or "").strip() or (
        "⚡ Ajuste rápido" if kid_lang == "es" else "⚡ Quick adjustment"
    )

    transaction = await PointsService.create_parent_adjustment(
        db,
        ParentAdjustment(
            user_id=adjustment.user_id,
            points=adjustment.points,
            reason=reason,
        ),
        parent_id=current_user.id,
        family_id=current_user.family_id,
    )

    # Tell the kid why their balance moved. Best-effort.
    try:
        from app.services.notification_service import NotificationService

        delta = (
            f"+{adjustment.points}" if adjustment.points > 0
            else str(adjustment.points)
        )
        await NotificationService.create_localized(
            db,
            family_id=current_user.family_id,
            key="points_adjusted",
            user_id=adjustment.user_id,
            params={"delta": delta, "reason": reason},
            link="/dashboard",
            lang=kid_lang,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "points quick-adjust notification failed", exc_info=True
        )

    return transaction


class StarModeUpdate(BaseModel):
    """Toggle payload for a kid's Star Mode young-kid display."""

    enabled: bool


@router.put("/{user_id}/star-mode", response_model=UserResponse)
async def update_star_mode(
    body: StarModeUpdate,
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a kid's Star Mode (young-kid display), parent only.

    Star Mode is pure presentation over the existing POINTS system: the kid
    dashboard + kiosk render points as big stars and hide peso/cash amounts.
    It is NOT a currency and never touches balances. CHILD/TEEN targets only.
    """
    from app.core.exceptions import ValidationException

    if user.role == UserRole.PARENT:
        raise ValidationException("Star Mode applies to CHILD/TEEN members only")
    user.star_mode = body.enabled
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user account (parent only)
    
    Cannot deactivate a parent if they are the only active parent in the family.
    """
    from sqlalchemy import select, and_, func
    from app.core.exceptions import ValidationException
    
    # Prevent self-deactivation
    if user.id == current_user.id:
        raise ValidationException("Cannot deactivate your own account")
    
    # If the user to deactivate is a parent, check if they're the last one
    if user.role == UserRole.PARENT:
        # Count active parents in the family (excluding the user being deactivated)
        result = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.family_id == user.family_id,
                    User.role == UserRole.PARENT,
                    User.is_active == True,
                    User.id != user.id
                )
            )
        )
        active_parent_count = result.scalar() or 0
        
        if active_parent_count == 0:
            raise ValidationException("Cannot deactivate the only active parent in the family")
    
    user = await AuthService.deactivate_user(db, user.id)
    return user


@router.put("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user: User = Depends(get_family_user),
    _: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Activate a user account (parent only)"""
    user = await AuthService.activate_user(db, user.id)
    return user


@router.put("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    role: str = None,
    db: AsyncSession = Depends(get_db),
):
    """Update user role (parent only)
    
    Valid roles: parent, teen, child
    """
    from app.core.exceptions import ValidationException
    
    if role is None:
        raise ValidationException("Role is required")
    
    # Validate role is valid
    try:
        UserRole[role.upper()]
    except KeyError:
        raise ValidationException(f"Invalid role. Must be one of: {', '.join([r.value for r in UserRole])}")
    
    # Prevent parent from changing their own role to non-parent
    if user.id == current_user.id and role.lower() != "parent":
        raise ValidationException("Cannot change your own role to non-parent")
    
    # Update the role
    updated_user = await AuthService.update_profile(
        db,
        user.id,
        {"role": role.lower()}
    )
    
    return updated_user


@router.post("/{user_id}/approve", response_model=UserResponse)
async def approve_pending_member(
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Approve a join-code member pending parental approval (parent only).

    The member can log in once approved. 400 if the account is not pending.
    """
    approved = await AuthService.approve_user(db, user)

    # Tell the kid their account is live (in-app; visible after first login).
    try:
        from app.services.notification_service import NotificationService

        await NotificationService.create_localized(
            db,
            family_id=approved.family_id,
            key="member_approved",
            user_id=approved.id,
            params={"parent": current_user.name},
            link="/dashboard",
            lang=approved.preferred_lang or "es",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "member-approved notification failed", exc_info=True
        )
    return approved


@router.post("/{user_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_pending_member(
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Reject a join-code member pending parental approval (parent only).

    Rejection DELETES the account (it never got in — nothing to keep).
    Only pending accounts can be rejected; established members go through
    the normal deactivate/delete endpoints instead.

    Open (PENDING/OVERDUE) task assignments held by the rejected account
    are deleted explicitly and the count is logged BEFORE the user row is
    removed — the FK is ondelete=CASCADE, so without this the rows would
    vanish silently. Pending members are excluded from the weekly shuffle,
    so such rows only exist as legacy data from before the approval gate;
    deleting (rather than reassigning) matches the cascade's end state
    while making it observable. Parents can re-shuffle to redistribute
    (the shuffle is idempotent for PENDING rows).
    """
    import logging

    from sqlalchemy import and_, delete as sql_delete

    from app.core.exceptions import ValidationException
    from app.models.task_assignment import TaskAssignment, AssignmentStatus
    from app.models.user import APPROVAL_PENDING

    if user.approval_status != APPROVAL_PENDING:
        raise ValidationException("User is not pending approval")

    result = await db.execute(
        sql_delete(TaskAssignment).where(
            and_(
                TaskAssignment.assigned_to == user.id,
                TaskAssignment.status.in_(
                    [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                ),
            )
        )
    )
    removed = result.rowcount or 0
    if removed:
        logging.getLogger(__name__).info(
            "reject_pending_member: removed %d open assignment(s) held by "
            "rejected pending user %s (family %s) before account deletion",
            removed,
            user.id,
            user.family_id,
        )

    await AuthService.delete_user(db, user.id)
    return None


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    confirm: str = "",
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account (parent only).

    Cascade-deletes all related records (tasks, points, history). Because
    this is irreversible — a real kid account was once lost to a single
    misclick and had to be restored from a DB backup — it is double-gated:

    1. The member must ALREADY be deactivated (deactivating is reversible,
       so the destructive step can never be the first click).
    2. ``confirm`` must match the member's name exactly (typed confirmation).

    Parents cannot delete themselves.
    """
    from app.core.exceptions import ValidationException

    # Prevent parents from deleting themselves
    if user.id == current_user.id:
        raise ValidationException("Cannot delete your own account")

    if user.is_active:
        raise ValidationException(
            "Primero desactiva la cuenta — borrar es permanente / "
            "Deactivate the account first — deletion is permanent"
        )

    if confirm.strip() != (user.name or "").strip():
        raise ValidationException(
            f"Escribe el nombre exacto ('{user.name}') para confirmar el "
            f"borrado permanente / Type the exact name ('{user.name}') to "
            "confirm permanent deletion"
        )

    await AuthService.delete_user(db, user.id)
    return None
