"""Onboarding routes — checklist state/dismiss + age-preset starter packs."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
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

# The per-module tours the frontend defines (buildModuleTour in
# frontend/src/lib/tourSteps.ts). An allowlist, not free text: without it every
# request could write an arbitrary string into users.completed_tours. Keep in
# step with the frontend — an id missing here makes its tour re-run forever.
TOUR_IDS = frozenset(
    {
        "budget-parent",
        "gigs-parent",
        "gigs-kid",
        "chores-parent",
        "rewards-kid",
    }
)


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


@router.post("/tours/{tour_id}/complete", status_code=204)
async def complete_module_tour(
    tour_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a per-module tour finished or skipped for the current user.

    Not parent-gated, unlike most of this router: the gig-board and rewards
    tours are kid-facing and ack through the same route.

    Idempotent — the frontend acks by sendBeacon on every exit path, and a
    replay acks again.
    """
    if tour_id not in TOUR_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown tour id: {tour_id}",
        )
    # Reassign rather than .append(): SQLAlchemy does not track mutations of a
    # JSON list in place, so appending would silently never persist.
    done = list(current_user.completed_tours or [])
    if tour_id not in done:
        current_user.completed_tours = [*done, tour_id]
        await db.commit()
    return Response(status_code=204)


@router.get("/analytics", response_model=OnboardingAnalytics)
async def get_onboarding_analytics(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent-facing onboarding funnel: tour completion per member + checklist."""
    family_id = to_uuid_required(current_user.family_id)
    return await OnboardingService.get_analytics(family_id, db)
