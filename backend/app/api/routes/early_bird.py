"""Early Bird (chore deadline) endpoints. HTTP only; logic in EarlyBirdService."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.exceptions import ForbiddenException
from app.models.user import User, UserRole
from app.schemas.early_bird import EarlyBirdMe, FamilyTeen, GrabListItem
from app.schemas.task_assignment import TaskAssignmentResponse
from app.services.early_bird_service import EarlyBirdService

router = APIRouter()

_KIDS = (UserRole.CHILD, UserRole.TEEN)


def _kid_only(user: User) -> User:
    if user.role not in _KIDS:
        raise ForbiddenException("kids_only")
    return user


@router.get("/me", response_model=EarlyBirdMe)
async def my_early_bird(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _kid_only(current_user)
    return await EarlyBirdService.me(db, current_user)


@router.get("/grabs", response_model=List[GrabListItem])
async def list_grabs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    # Any authenticated family member, parents included (not kid-only like /me).
    return await EarlyBirdService.grab_list(db, current_user)


@router.post("/grabs/{assignment_id}/take", response_model=TaskAssignmentResponse)
async def take_grab(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Any active family member may take (parents included): eligibility is
    # EarlyBirdService.can_take's call, not the route's.
    # Refusals are FamilyAppExceptions: the global handlers map them to
    # 404/409/403/400 with the reason key in "message".
    return await EarlyBirdService.take(
        db, current_user.family_id, current_user, assignment_id
    )


@router.get("/family", response_model=List[FamilyTeen])
async def family_overview(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await EarlyBirdService.family_overview(db, current_user)
