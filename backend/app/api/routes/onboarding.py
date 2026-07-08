"""Onboarding routes — checklist state/dismiss + age-preset starter packs."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.onboarding import (
    OnboardingState,
    OnboardingEventCreate,
    OnboardingAnalytics,
    StarterPackApplyRequest,
    StarterPackApplyResult,
    StarterPackList,
)
from app.services.onboarding_service import OnboardingService
from app.services.starter_pack_service import StarterPackService

router = APIRouter()


@router.get("/starter-packs", response_model=StarterPackList)
async def list_starter_packs(
    current_user: User = Depends(require_parent_role),
):
    """Curated ES/MX starter packs by kid age band (static data)."""
    return StarterPackService.list_packs()


@router.post("/starter-packs/apply", response_model=StarterPackApplyResult)
async def apply_starter_pack(
    payload: StarterPackApplyRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create the selected pack items for the family (idempotent by title)."""
    family_id = to_uuid_required(current_user.family_id)
    return await StarterPackService.apply(
        db, family_id, to_uuid_required(current_user.id), payload
    )


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


@router.post("/events", status_code=204)
async def record_onboarding_event(
    payload: OnboardingEventCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a welcome-tour funnel event (any family member)."""
    await OnboardingService.record_event(
        current_user, payload.event_type, payload.step_index, db
    )
    return Response(status_code=204)


@router.get("/analytics", response_model=OnboardingAnalytics)
async def get_onboarding_analytics(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent-facing onboarding funnel: tour completion per member + checklist."""
    family_id = to_uuid_required(current_user.family_id)
    return await OnboardingService.get_analytics(family_id, db)
