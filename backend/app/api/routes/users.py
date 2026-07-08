"""
User management routes

Handles user profile operations and points management.
"""

from fastapi import APIRouter, Depends, status
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
    """
    from app.core.exceptions import ValidationException
    from app.models.user import APPROVAL_PENDING

    if user.approval_status != APPROVAL_PENDING:
        raise ValidationException("User is not pending approval")

    await AuthService.delete_user(db, user.id)
    return None


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user: User = Depends(get_family_user),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a user account (parent only)
    
    This will cascade delete all related records (tasks, points, etc.).
    Parents cannot delete themselves.
    """
    # Prevent parents from deleting themselves
    if user.id == current_user.id:
        from app.core.exceptions import ValidationException
        raise ValidationException("Cannot delete your own account")
    
    await AuthService.delete_user(db, user.id)
    return None
