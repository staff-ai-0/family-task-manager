"""Early Bird (chore deadline) endpoints. HTTP only; logic in EarlyBirdService."""
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.exceptions import ForbiddenException
from app.models.user import User, UserRole
from app.schemas.early_bird import EarlyBirdMe, FamilyTeen
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


@router.get("/family", response_model=List[FamilyTeen])
async def family_overview(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await EarlyBirdService.family_overview(db, current_user)
