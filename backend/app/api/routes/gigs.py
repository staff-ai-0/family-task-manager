from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
from app.models.gig import GigClaimStatus
from app.services.gig_offering_service import GigOfferingService
from app.services.gig_claim_service import GigClaimService
from app.core.exceptions import ValidationException

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────

class GigOfferingCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    points: int = Field(..., gt=0)
    difficulty: int = Field(1, ge=1, le=3)
    category: str = "other"
    allowed_roles: Optional[List[str]] = None


class GigOfferingUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    points: Optional[int] = Field(None, gt=0)
    difficulty: Optional[int] = Field(None, ge=1, le=3)
    category: Optional[str] = None
    allowed_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class GigOfferingResponse(BaseModel):
    id: UUID
    family_id: UUID
    title: str
    description: Optional[str]
    points: int
    difficulty: int
    category: str
    allowed_roles: Optional[List[str]]
    is_active: bool

    class Config:
        from_attributes = True


class GigClaimResponse(BaseModel):
    id: UUID
    gig_id: UUID
    family_id: UUID
    claimed_by: UUID
    status: str
    proof_text: Optional[str]
    proof_image_url: Optional[str]
    points_awarded: Optional[int]
    approved_by: Optional[UUID]
    approval_notes: Optional[str]
    # Enriched fields (populated on list endpoints)
    claimer_name: Optional[str] = None
    gig_title: Optional[str] = None
    gig_points: Optional[int] = None

    class Config:
        from_attributes = True


class EnrichedOfferingResponse(BaseModel):
    offering: GigOfferingResponse
    my_claim: Optional[GigClaimResponse]


class CompleteClaimRequest(BaseModel):
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None


class ApproveClaimRequest(BaseModel):
    approved: bool
    notes: Optional[str] = None


# ── Offering endpoints ───────────────────────────────────────────────────────

@router.get("/offerings", response_model=List[EnrichedOfferingResponse])
async def list_offerings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    items = await GigOfferingService.list_for_family(db, family_id, user_id)
    return [
        EnrichedOfferingResponse(
            offering=GigOfferingResponse.model_validate(item["offering"]),
            my_claim=GigClaimResponse.model_validate(item["my_claim"]) if item["my_claim"] else None,
        )
        for item in items
    ]


@router.post("/offerings", response_model=GigOfferingResponse, status_code=status.HTTP_201_CREATED)
async def create_offering(
    data: GigOfferingCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    offering = await GigOfferingService.create(
        db,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
        **data.model_dump(),
    )
    return offering


@router.put("/offerings/{offering_id}", response_model=GigOfferingResponse)
async def update_offering(
    offering_id: UUID,
    data: GigOfferingUpdate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    offering = await GigOfferingService.update(
        db,
        offering_id=offering_id,
        family_id=to_uuid_required(current_user.family_id),
        **{k: v for k, v in data.model_dump().items() if v is not None},
    )
    return offering


@router.delete("/offerings/{offering_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_offering(
    offering_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await GigOfferingService.deactivate(
        db,
        offering_id=offering_id,
        family_id=to_uuid_required(current_user.family_id),
    )


# ── Claim endpoints ──────────────────────────────────────────────────────────

@router.post("/offerings/{offering_id}/claim", response_model=GigClaimResponse, status_code=status.HTTP_201_CREATED)
async def claim_offering(
    offering_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import UserRole
    if current_user.role == UserRole.PARENT:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Padres no pueden reclamar gigs")
    try:
        claim = await GigClaimService.claim(
            db,
            gig_id=offering_id,
            user_id=to_uuid_required(current_user.id),
            family_id=to_uuid_required(current_user.family_id),
        )
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return claim


@router.get("/claims/pending-approvals", response_model=List[GigClaimResponse])
async def pending_approvals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    items = await GigClaimService.get_pending_approvals(
        db, family_id=to_uuid_required(current_user.family_id)
    )
    return [
        GigClaimResponse(
            **{k: v for k, v in GigClaimResponse.model_validate(item["claim"]).model_dump().items()},
            claimer_name=item["claimer_name"],
            gig_title=item["gig_title"],
            gig_points=item["gig_points"],
        )
        for item in items
    ]


@router.get("/claims/my", response_model=List[GigClaimResponse])
async def my_claims(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items = await GigClaimService.get_my_claims_enriched(
        db,
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
    )
    return [
        GigClaimResponse(
            **{k: v for k, v in GigClaimResponse.model_validate(item["claim"]).model_dump().items()},
            gig_title=item["gig_title"],
            gig_points=item["gig_points"],
        )
        for item in items
    ]


@router.post("/claims/{claim_id}/complete", response_model=GigClaimResponse)
async def complete_claim(
    claim_id: UUID,
    data: CompleteClaimRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    claim = await GigClaimService.complete(
        db,
        claim_id=claim_id,
        user_id=to_uuid_required(current_user.id),
        proof_text=data.proof_text,
        proof_image_url=data.proof_image_url,
    )
    return claim


@router.post("/claims/{claim_id}/unclaim", status_code=status.HTTP_204_NO_CONTENT)
async def unclaim(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await GigClaimService.unclaim(
        db,
        claim_id=claim_id,
        user_id=to_uuid_required(current_user.id),
    )


@router.post("/claims/{claim_id}/approve", response_model=GigClaimResponse)
async def approve_claim(
    claim_id: UUID,
    data: ApproveClaimRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    claim = await GigClaimService.approve(
        db,
        claim_id=claim_id,
        approver_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        approved=data.approved,
        notes=data.notes,
    )
    return claim
