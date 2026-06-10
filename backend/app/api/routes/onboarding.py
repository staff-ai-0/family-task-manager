"""Onboarding checklist routes — GET state, POST dismiss."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.onboarding import OnboardingState
from app.services.onboarding_service import OnboardingService

router = APIRouter()


@router.get("", response_model=OnboardingState)
async def get_onboarding_state(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    return await OnboardingService.get_state(family_id, db)


@router.post("/dismiss", status_code=204)
async def dismiss_onboarding(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    await OnboardingService.dismiss(family_id, db)
    return Response(status_code=204)
