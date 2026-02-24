"""
Task assignment routes

Handles weekly shuffle, assignment queries, completion with bonus gating,
and daily progress tracking.
"""

from fastapi import APIRouter, Depends, status, Query
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
    TaskAssignmentResponse,
    TaskAssignmentWithDetails,
    DailyProgressResponse,
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
    assignments = await TaskAssignmentService.list_assignments_for_week(
        db,
        family_id=to_uuid_required(current_user.family_id),
        week_of=target,
        user_id=user_id,
        status=status,
    )

    return [_assignment_to_detail(a) for a in assignments]


@router.get("/today", response_model=List[TaskAssignmentWithDetails])
async def list_today_assignments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    user_id: Optional[UUID] = Query(None, description="Filter by user (defaults to current user)"),
):
    """List assignments for today (defaults to current user)"""
    target_user = user_id or to_uuid_required(current_user.id)
    assignments = await TaskAssignmentService.list_assignments_for_date(
        db,
        family_id=to_uuid_required(current_user.family_id),
        target_date=date.today(),
        user_id=target_user,
    )

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


@router.patch("/{assignment_id}/complete", response_model=TaskAssignmentWithDetails)
async def complete_assignment(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark an assignment as completed.
    Awards points automatically. Bonus tasks require all required tasks to be done first.
    """
    assignment = await TaskAssignmentService.complete_assignment(
        db,
        assignment_id,
        family_id=to_uuid_required(current_user.family_id),
        user_id=to_uuid_required(current_user.id),
    )

    # Re-fetch with template loaded
    assignment = await TaskAssignmentService.get_assignment(
        db, assignment_id, to_uuid_required(current_user.family_id)
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
    """Convert a TaskAssignment ORM object to TaskAssignmentWithDetails dict"""
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
        "template_points": template.points if template else 0,
        "template_is_bonus": template.is_bonus if template else False,
        # User details
        "assigned_user_name": assigned_user.name if assigned_user else "",
        # Computed
        "is_overdue": assignment.is_overdue,
        "can_complete": assignment.can_complete,
    }
