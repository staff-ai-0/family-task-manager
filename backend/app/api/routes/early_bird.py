"""Early Bird (chore deadline) endpoints. HTTP only; logic in EarlyBirdService."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.user import User, UserRole
from app.schemas.early_bird import EarlyBirdMe, FamilyTeen
from app.schemas.task_assignment import TaskAssignmentResponse
from app.services.early_bird_service import EarlyBirdService

router = APIRouter()

_KIDS = (UserRole.CHILD, UserRole.TEEN)


def _kid_only(user: User) -> User:
    if user.role not in _KIDS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="kids_only")
    return user


@router.get("/me", response_model=EarlyBirdMe)
async def my_early_bird(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _kid_only(current_user)
    return await EarlyBirdService.me(db, current_user)


@router.post("/grabs/{assignment_id}/take", response_model=TaskAssignmentResponse)
async def take_grab(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _kid_only(current_user)
    try:
        return await EarlyBirdService.take(
            db, current_user.family_id, current_user, assignment_id
        )
    except NotFoundException as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e) or "not_found")
    except ConflictException as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    except ForbiddenException as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValidationException as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/family", response_model=List[FamilyTeen])
async def family_overview(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> list:
    return await EarlyBirdService.family_overview(db, current_user)
