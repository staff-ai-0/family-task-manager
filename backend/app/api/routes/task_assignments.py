"""
Task assignment routes

Handles weekly shuffle, assignment queries, completion with bonus gating,
and daily progress tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import date
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.services.task_assignment_service import TaskAssignmentService
from app.schemas.task_assignment import (
    ShuffleRequest,
    ShuffleResponse,
    ShufflePreviewResponse,
    TaskAssignmentResponse,
    TaskAssignmentWithDetails,
    DailyProgressResponse,
    AssignmentPatch,
    CompleteAssignmentRequest,
    ApprovalDecision,
    GigApprovalRow,
)
from app.models import User
from app.models.task_assignment import AssignmentStatus

router = APIRouter()


# ─── Shuffle ─────────────────────────────────────────────────────────

@router.post("/shuffle", response_model=ShuffleResponse)
async def shuffle_tasks(
    request: ShuffleRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate weekly task assignments by shuffling templates (parent only).
    Deletes existing PENDING assignments for the target week and creates new ones.
    """
    assignments, skipped = await TaskAssignmentService.shuffle_tasks_detailed(
        db,
        family_id=to_uuid_required(current_user.family_id),
        week_of=request.week_of,
    )

    week_of = assignments[0].week_of if assignments else (request.week_of or date.today())

    return ShuffleResponse(
        week_of=week_of,
        assignments_created=len(assignments),
        assignments=assignments,
        skipped_templates=skipped,
    )


@router.get("/shuffle/preview", response_model=ShufflePreviewResponse)
async def preview_shuffle(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
    week_of: Optional[date] = Query(None, description="Any date in the target week"),
):
    """
    Dry-run shuffle: returns the proposed plan + per-member point totals without
    persisting anything. Use to preview before POST /shuffle.
    """
    preview = await TaskAssignmentService.preview_shuffle(
        db,
        family_id=to_uuid_required(current_user.family_id),
        week_of=week_of,
    )
    return preview


# ─── Query Assignments ──────────────────────────────────────────────

@router.get("/week", response_model=List[TaskAssignmentWithDetails])
async def list_week_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    week_of: Optional[date] = Query(None, description="Any date in the target week"),
    user_id: Optional[UUID] = Query(None, description="Filter by assigned user"),
    status: Optional[AssignmentStatus] = Query(None, description="Filter by status"),
):
    """List all assignments for a given week"""
    target = week_of or date.today()
    family_id = to_uuid_required(current_user.family_id)
    assignments = await TaskAssignmentService.list_assignments_for_week(
        db,
        family_id=family_id,
        week_of=target,
        user_id=user_id,
        status=status,
    )

    # Per-user, per-date lock cache. Only today (or future) can be locked;
    # historical dates always render unlocked since the day has passed.
    # "today" is computed in the viewer's family timezone.
    today = await TaskAssignmentService._user_local_today(db, current_user.id)
    lock_cache: dict[tuple, bool] = {}
    for a in assignments:
        is_bonus = a.template.is_bonus if a.template else False
        if is_bonus and a.assigned_date == today and a.status != AssignmentStatus.COMPLETED:
            key = (a.assigned_to, a.assigned_date)
            if key not in lock_cache:
                lock_cache[key] = await TaskAssignmentService.has_open_mandatory_through(
                    db, a.assigned_to, family_id, a.assigned_date
                )
            a._is_locked = lock_cache[key]
        else:
            a._is_locked = False

    return [_assignment_to_detail(a) for a in assignments]


@router.get("/today", response_model=List[TaskAssignmentWithDetails])
async def list_today_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None, description="Filter by user (defaults to current user)"),
):
    """List assignments for today (defaults to current user)"""
    target_user = user_id or to_uuid_required(current_user.id)
    family_id = to_uuid_required(current_user.family_id)
    today = await TaskAssignmentService._user_local_today(db, target_user)
    assignments = await TaskAssignmentService.list_assignments_for_date(
        db,
        family_id=family_id,
        target_date=today,
        user_id=target_user,
    )

    # Compute lock state once per (user, date) — needed because /today may
    # include multiple users when filtered by user_id query param.
    lock_cache: dict[tuple, bool] = {}
    for a in assignments:
        is_bonus = a.template.is_bonus if a.template else False
        if is_bonus and a.status != AssignmentStatus.COMPLETED:
            key = (a.assigned_to, a.assigned_date)
            if key not in lock_cache:
                lock_cache[key] = await TaskAssignmentService.has_open_mandatory_through(
                    db, a.assigned_to, family_id, a.assigned_date
                )
            a._is_locked = lock_cache[key]
        else:
            a._is_locked = False

    return [_assignment_to_detail(a) for a in assignments]


@router.get("/progress", response_model=DailyProgressResponse)
async def get_daily_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    target_date: Optional[date] = Query(None, description="Date to check (defaults to today)"),
    user_id: Optional[UUID] = Query(None, description="User to check (defaults to current user)"),
):
    """Get daily progress summary with bonus gating status"""
    target_user = user_id or to_uuid_required(current_user.id)
    progress = await TaskAssignmentService.get_daily_progress(
        db,
        user_id=target_user,
        family_id=to_uuid_required(current_user.family_id),
        target_date=target_date,
    )

    # Convert assignments to detailed format
    progress["assignments"] = [_assignment_to_detail(a) for a in progress["assignments"]]
    progress["overdue_assignments"] = [
        _assignment_to_detail(a) for a in progress.get("overdue_assignments", [])
    ]

    return DailyProgressResponse(**progress)


# ─── Gig proof upload ────────────────────────────────────────────────
# Must also be registered BEFORE @router.get("/{assignment_id}").

@router.post("/proof-upload")
async def upload_gig_proof(
    file: UploadFile = File(..., description="Proof image (JPEG, PNG, WebP). Max 5MB."),
    current_user: User = Depends(get_current_user),
):
    """Upload a proof image for a gig. Returns the URL to store on the assignment.

    Stateless — the URL is not bound to a specific assignment here; the caller
    submits the URL via the `/complete` endpoint's proof_image_url field.
    """
    import uuid as _uuid
    import os as _os

    from starlette.concurrency import run_in_threadpool

    from app.core.config import settings
    from app.core.thumbnails import make_webp_thumbnail, thumb_filename
    from app.core.upload_validation import (
        read_upload_capped,
        assert_allowed_type,
        MAX_PROOF_BYTES,
    )

    allowed = {"image/jpeg", "image/png", "image/webp"}
    content_type = (file.content_type or "").lower()
    if content_type not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported type {content_type}")

    body = await read_upload_capped(file, MAX_PROOF_BYTES)
    # Authoritative check: sniff the real bytes, not the client-declared type.
    real_type = assert_allowed_type(body, allowed)

    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[real_type]
    fname = f"{_uuid.uuid4().hex}.{ext}"
    dest_dir = _os.path.join(settings.UPLOADS_ROOT, "gig-proofs")
    _os.makedirs(dest_dir, exist_ok=True)
    dest = _os.path.join(dest_dir, fname)
    with open(dest, "wb") as fh:
        fh.write(body)

    # Generate a ~200px WebP thumbnail alongside the original so list/approval
    # views load fast. CPU-bound → run off the event loop. A malformed image
    # yields None; we simply skip the thumb and the serving route falls back to
    # the full image.
    thumb = await run_in_threadpool(make_webp_thumbnail, body)
    if thumb:
        with open(_os.path.join(dest_dir, thumb_filename(fname)), "wb") as fh:
            fh.write(thumb)

    return {"proof_image_url": f"/uploads/gig-proofs/{fname}"}


# ─── Approvals ───────────────────────────────────────────────────────
# NOTE: must be registered BEFORE @router.get("/{assignment_id}") so FastAPI
# doesn't try to coerce "pending-approvals" into a UUID.

@router.get("/pending-approvals", response_model=List[GigApprovalRow])
async def list_pending_approvals(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """List gigs awaiting parent approval (parents only)."""
    family_id = to_uuid_required(current_user.family_id)
    rows = await TaskAssignmentService.list_pending_approvals(db, family_id)

    # One query for assignee names — avoids N+1.
    user_ids = list({r.assigned_to for r in rows})
    user_names: dict = {}
    if user_ids:
        q = sa_select(User.id, User.name).where(User.id.in_(user_ids))
        user_names = {uid: name for uid, name in (await db.execute(q)).all()}

    return [
        GigApprovalRow(
            assignment_id=r.id,
            template_id=r.template_id,
            template_title=r.template.title if r.template else "",
            template_is_bonus=r.template.is_bonus if r.template else True,
            points=r.template.award_points_per_completer if r.template else 0,
            assigned_to=r.assigned_to,
            assigned_to_name=user_names.get(r.assigned_to, ""),
            completed_at=r.completed_at,
            proof_text=r.proof_text,
            proof_image_url=r.proof_image_url,
            ai_validation_score=r.ai_validation_score,
            ai_validation_notes=r.ai_validation_notes,
        )
        for r in rows
    ]


@router.get("/blocking-rewards", response_model=List[str])
async def list_blocking_rewards(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Titles of tasks (templates with blocks_rewards=True) that currently lock
    reward redemption for the caller. Empty list = nothing blocking.
    """
    from app.models.task_assignment import TaskAssignment, AssignmentStatus
    from app.models.task_template import TaskTemplate
    from sqlalchemy import and_

    family_id = to_uuid_required(current_user.family_id)
    user_id = to_uuid_required(current_user.id)
    q = (
        sa_select(TaskTemplate.title)
        .join(TaskAssignment, TaskAssignment.template_id == TaskTemplate.id)
        .where(
            and_(
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.family_id == family_id,
                TaskAssignment.status.in_(
                    [AssignmentStatus.PENDING, AssignmentStatus.OVERDUE]
                ),
                TaskTemplate.blocks_rewards.is_(True),
            )
        )
        .distinct()
        .limit(10)
    )
    rows = (await db.execute(q)).all()
    return [r[0] for r in rows]


# ─── Assignment Actions ──────────────────────────────────────────────

@router.get("/{assignment_id}", response_model=TaskAssignmentWithDetails)
async def get_assignment(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get an assignment by ID"""
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, to_uuid_required(current_user.family_id)
    )
    return _assignment_to_detail(assignment)


@router.patch("/{assignment_id}", response_model=TaskAssignmentWithDetails)
async def patch_assignment(
    assignment_id: UUID,
    patch: AssignmentPatch,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """
    Parent edit on a single assignment: reassign, reschedule, or cancel/revive.
    Completion goes through /complete (which awards points).
    """
    assignment = await TaskAssignmentService.patch_assignment(
        db,
        assignment_id,
        family_id=to_uuid_required(current_user.family_id),
        assigned_to=patch.assigned_to,
        assigned_date=patch.assigned_date,
        status=patch.status,
    )
    return _assignment_to_detail(assignment)


@router.patch("/{assignment_id}/complete", response_model=TaskAssignmentWithDetails)
async def complete_assignment(
    assignment_id: UUID,
    payload: Optional[CompleteAssignmentRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark an assignment as completed.

    Mandatory tasks complete silently (no points). Gigs (is_bonus=true) require
    `proof_text` in the body and enter PENDING approval — points are credited
    only when a parent approves via POST /{id}/approve.
    """
    family_id = to_uuid_required(current_user.family_id)
    await TaskAssignmentService.complete_assignment(
        db,
        assignment_id,
        family_id=family_id,
        user_id=to_uuid_required(current_user.id),
        proof_text=(payload.proof_text if payload else None),
        proof_image_url=(payload.proof_image_url if payload else None),
    )

    # Re-fetch with template loaded
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, family_id
    )
    return _assignment_to_detail(assignment)


@router.post("/{assignment_id}/claim", response_model=TaskAssignmentWithDetails)
async def claim_assignment(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reserve a gig before working on it. Transitions PENDING → CLAIMED.
    Mandatory rows reject; gating still applies."""
    family_id = to_uuid_required(current_user.family_id)
    await TaskAssignmentService.claim_gig(
        db,
        assignment_id,
        family_id=family_id,
        user_id=to_uuid_required(current_user.id),
    )
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, family_id
    )
    return _assignment_to_detail(assignment)


@router.post("/{assignment_id}/unclaim", response_model=TaskAssignmentWithDetails)
async def unclaim_assignment(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Release a claim. Transitions CLAIMED → PENDING."""
    family_id = to_uuid_required(current_user.family_id)
    await TaskAssignmentService.unclaim_gig(
        db,
        assignment_id,
        family_id=family_id,
        user_id=to_uuid_required(current_user.id),
    )
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, family_id
    )
    return _assignment_to_detail(assignment)


@router.post("/{assignment_id}/approve", response_model=TaskAssignmentWithDetails)
async def approve_assignment(
    assignment_id: UUID,
    decision: ApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Parent decision on a pending gig. Approve credits points; reject does not.
    """
    family_id = to_uuid_required(current_user.family_id)
    await TaskAssignmentService.approve_gig(
        db,
        assignment_id=assignment_id,
        family_id=family_id,
        parent_id=to_uuid_required(current_user.id),
        approve=decision.approve,
        notes=decision.notes,
    )
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, family_id
    )
    return _assignment_to_detail(assignment)


@router.post("/check-overdue", response_model=List[TaskAssignmentResponse])
async def check_overdue_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check for overdue assignments and update status"""
    assignments = await TaskAssignmentService.check_overdue_assignments(
        db, to_uuid_required(current_user.family_id)
    )
    return assignments


# ─── Helpers ─────────────────────────────────────────────────────────

def _assignment_to_detail(assignment) -> dict:
    """Convert a TaskAssignment ORM object to TaskAssignmentWithDetails dict.

    Synthetic enrichment: callers may set assignment._is_locked = True on the
    Python object before calling this helper (used by /today and /week to
    surface bonus-gating state without re-querying).
    """
    template = assignment.template
    assigned_user = getattr(assignment, "assigned_user", None)
    return {
        "id": assignment.id,
        "family_id": assignment.family_id,
        "template_id": assignment.template_id,
        "assigned_to": assignment.assigned_to,
        "status": assignment.status,
        "assigned_date": assignment.assigned_date,
        "due_date": assignment.due_date,
        "week_of": assignment.week_of,
        "completed_at": assignment.completed_at,
        "created_at": assignment.created_at,
        "updated_at": assignment.updated_at,
        # Template details
        "template_title": template.title if template else "",
        "template_description": template.description if template else None,
        "template_title_es": template.title_es if template else None,
        "template_description_es": template.description_es if template else None,
        # Effective (effort-multiplied) points — what will actually be
        # awarded; showing raw base points made the credit look wrong.
        "template_points": template.effective_points if template else 0,
        "template_effort_level": template.effort_level if template else 1,
        "template_is_bonus": template.is_bonus if template else False,
        "template_requires_proof": bool(template.requires_proof) if template else False,
        "template_gig_mode": (template.gig_mode if template else "claim") or "claim",
        "template_collaboration_min_count": (
            template.collaboration_min_count if template else 2
        ),
        # User details
        "assigned_user_name": assigned_user.name if assigned_user else "",
        # Computed
        "is_overdue": assignment.is_overdue,
        "can_complete": assignment.can_complete,
        # Gig gating + approval enrichment
        "is_locked": bool(getattr(assignment, "_is_locked", False)),
        "approval_status": (
            assignment.approval_status.value
            if getattr(assignment, "approval_status", None)
            else "none"
        ),
        "proof_text": getattr(assignment, "proof_text", None),
        "proof_image_url": getattr(assignment, "proof_image_url", None),
    }
