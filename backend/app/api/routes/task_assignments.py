"""
Task assignment routes

Handles weekly shuffle, assignment queries, completion with bonus gating,
and daily progress tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
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
from app.models.user import UserRole
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
    assignments = await TaskAssignmentService.shuffle_tasks(
        db,
        family_id=to_uuid_required(current_user.family_id),
        week_of=request.week_of,
    )

    week_of = assignments[0].week_of if assignments else (request.week_of or date.today())

    return ShuffleResponse(
        week_of=week_of,
        assignments_created=len(assignments),
        assignments=assignments,
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
    today = date.today()
    lock_cache: dict[tuple, bool] = {}
    for a in assignments:
        is_bonus = a.template.is_bonus if a.template else False
        if is_bonus and a.assigned_date == today and a.status != AssignmentStatus.COMPLETED:
            key = (a.assigned_to, a.assigned_date)
            if key not in lock_cache:
                all_done = await TaskAssignmentService.check_all_required_done_today(
                    db, a.assigned_to, family_id, a.assigned_date
                )
                lock_cache[key] = not all_done
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
    assignments = await TaskAssignmentService.list_assignments_for_date(
        db,
        family_id=family_id,
        target_date=date.today(),
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
                all_done = await TaskAssignmentService.check_all_required_done_today(
                    db, a.assigned_to, family_id, a.assigned_date
                )
                lock_cache[key] = not all_done
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

    return DailyProgressResponse(**progress)


# ─── Approvals ───────────────────────────────────────────────────────
# NOTE: must be registered BEFORE @router.get("/{assignment_id}") so FastAPI
# doesn't try to coerce "pending-approvals" into a UUID.

@router.get("/pending-approvals", response_model=List[GigApprovalRow])
async def list_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List gigs awaiting parent approval (parents only)."""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(status_code=403, detail="Parents only")

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
            points=r.template.points if r.template else 0,
            assigned_to=r.assigned_to,
            assigned_to_name=user_names.get(r.assigned_to, ""),
            completed_at=r.completed_at,
            proof_text=r.proof_text,
        )
        for r in rows
    ]


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
    )

    # Re-fetch with template loaded
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
        "template_points": template.points if template else 0,
        "template_is_bonus": template.is_bonus if template else False,
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
    }
