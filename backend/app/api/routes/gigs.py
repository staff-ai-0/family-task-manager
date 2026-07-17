from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from uuid import UUID
from datetime import date, datetime

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models import User
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
    # False (default) = single-slot: first approved claim closes the gig.
    allow_multiple: bool = False
    # Advisory payout rhythm (reminders + payout-screen grouping only; never
    # blocks an early payout). Defaults to immediate so older clients that
    # don't send this field keep today's behavior.
    payout_cadence: Literal["immediate", "weekly", "biweekly", "monthly"] = "immediate"


class GigOfferingUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    points: Optional[int] = Field(None, gt=0)
    difficulty: Optional[int] = Field(None, ge=1, le=3)
    category: Optional[str] = None
    allowed_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None
    allow_multiple: Optional[bool] = None
    payout_cadence: Optional[Literal["immediate", "weekly", "biweekly", "monthly"]] = None


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
    allow_multiple: bool = False
    payout_cadence: str = "immediate"
    status: str = "approved"
    review_notes: Optional[str] = None
    created_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class GigProposalCreate(BaseModel):
    """Kid-proposed gig draft (W4.4). Kept intentionally small: title + the
    suggested pay; parents can edit on approval."""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: int = Field(..., gt=0, le=1000, description="Suggested pay in $MXN (1 pt = $1)")
    difficulty: int = Field(1, ge=1, le=3)
    category: str = "other"


class GigProposalReview(BaseModel):
    approve: bool
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, gt=0, le=1000)
    notes: Optional[str] = Field(None, max_length=500)


class GigProposalRow(BaseModel):
    offering: GigOfferingResponse
    proposer_name: str = ""


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
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    # Enriched fields (populated on list endpoints)
    claimer_name: Optional[str] = None
    gig_title: Optional[str] = None
    gig_points: Optional[int] = None
    # Duplicate-pay guardrail: who already got paid for this same gig.
    already_awarded_to: Optional[str] = None
    # Comment-thread badge (populated by list endpoints).
    comment_count: Optional[int] = None

    class Config:
        from_attributes = True


class EnrichedOfferingResponse(BaseModel):
    offering: GigOfferingResponse
    my_claim: Optional[GigClaimResponse]
    # Kids with an ACTIVE (claimed/completed) claim — "Ariana ya la está haciendo".
    active_claimers: List[str] = []


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
            active_claimers=item.get("active_claimers", []),
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
        acting_user_id=to_uuid_required(current_user.id),
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


# ── Kid-proposed gigs (W4.4) ─────────────────────────────────────────────────
# NOTE: registered before the {offering_id}-parameterized claim route so the
# literal 'proposals' segment can never be swallowed by a UUID param.

@router.post("/offerings/propose", response_model=GigOfferingResponse, status_code=status.HTTP_201_CREATED)
async def propose_offering(
    data: GigProposalCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """TEEN/CHILD proposes a gig. Lands as a DRAFT awaiting parent review —
    parents are notified; it is not claimable until approved."""
    from app.models.user import UserRole
    if current_user.role == UserRole.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Los padres crean gigs directamente, no propuestas",
        )
    offering = await GigOfferingService.propose(
        db,
        family_id=to_uuid_required(current_user.family_id),
        created_by=to_uuid_required(current_user.id),
        **data.model_dump(),
    )
    return offering


@router.get("/offerings/proposals/mine", response_model=List[GigOfferingResponse])
async def my_proposals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own pending/rejected proposals (approved ones show on the
    board itself)."""
    return await GigOfferingService.list_my_proposals(
        db,
        family_id=to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
    )


@router.get("/offerings/proposals/pending", response_model=List[GigProposalRow])
async def pending_proposals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    items = await GigOfferingService.list_pending_proposals(
        db, family_id=to_uuid_required(current_user.family_id)
    )
    return [
        GigProposalRow(
            offering=GigOfferingResponse.model_validate(item["offering"]),
            proposer_name=item["proposer_name"],
        )
        for item in items
    ]


@router.post("/offerings/{offering_id}/review", response_model=GigOfferingResponse)
async def review_proposal(
    offering_id: UUID,
    data: GigProposalReview,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Parent approves (optionally editing title/description/points) or
    rejects a kid proposal. The kid is notified either way."""
    offering = await GigOfferingService.review_proposal(
        db,
        offering_id=offering_id,
        family_id=to_uuid_required(current_user.family_id),
        reviewer_id=to_uuid_required(current_user.id),
        approve=data.approve,
        title=data.title,
        description=data.description,
        points=data.points,
        notes=data.notes,
    )
    return offering


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
            **GigClaimResponse.model_validate(item["claim"]).model_dump(
                exclude={
                    "claimer_name",
                    "gig_title",
                    "gig_points",
                    "already_awarded_to",
                }
            ),
            claimer_name=item["claimer_name"],
            gig_title=item["gig_title"],
            gig_points=item["gig_points"],
            already_awarded_to=item.get("already_awarded_to"),
        )
        for item in items
    ]


@router.get("/claims/family", response_model=List[GigClaimResponse])
async def family_claims(
    on: Optional[date] = Query(None, description="Filter to one UTC day (approved→completed→created)"),
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """All the family's gig claims (parent oversight / day review)."""
    items = await GigClaimService.list_family_claims(
        db, family_id=to_uuid_required(current_user.family_id), on=on
    )
    return [
        GigClaimResponse(
            **GigClaimResponse.model_validate(item["claim"]).model_dump(
                exclude={
                    "claimer_name",
                    "gig_title",
                    "gig_points",
                    "already_awarded_to",
                    "comment_count",
                }
            ),
            claimer_name=item["claimer_name"],
            gig_title=item["gig_title"],
            gig_points=item["gig_points"],
            comment_count=item.get("comment_count", 0),
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
            **GigClaimResponse.model_validate(item["claim"]).model_dump(
                exclude={"gig_title", "gig_points", "comment_count"}
            ),
            gig_title=item["gig_title"],
            gig_points=item["gig_points"],
            comment_count=item.get("comment_count", 0),
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


# ---------------------------------------------------------------------------
# Claim comment threads (parent ↔ kid conversation about a completed gig)
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=1000)


class CommentOut(BaseModel):
    id: UUID
    author_id: Optional[UUID]
    author_name: str
    body: str
    created_at: datetime


@router.get("/claims/{claim_id}/comments", response_model=List[CommentOut])
async def list_claim_comments(
    claim_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Comments on a claim (family parents + the claim owner)."""
    items = await GigClaimService.list_comments(
        db, to_uuid_required(current_user.family_id), claim_id, current_user
    )
    return [CommentOut(**i) for i in items]


@router.post(
    "/claims/{claim_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_claim_comment(
    claim_id: UUID,
    data: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a comment; notifies the other side (parent ↔ kid)."""
    item = await GigClaimService.add_comment(
        db,
        to_uuid_required(current_user.family_id),
        claim_id,
        current_user,
        data.body,
    )
    return CommentOut(**item)
