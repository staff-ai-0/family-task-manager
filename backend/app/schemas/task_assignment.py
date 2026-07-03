"""
TaskAssignment Pydantic schemas

Request and response models for task assignment operations.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID

from app.models.task_assignment import AssignmentStatus
from app.schemas.base import FamilyEntityResponse


# Request schemas
class AssignmentComplete(BaseModel):
    """Schema for marking an assignment as completed"""

    pass  # No extra fields needed, user comes from auth


class ShuffleRequest(BaseModel):
    """Schema for triggering weekly shuffle"""

    week_of: Optional[date] = Field(
        None,
        description="Monday of the week to generate assignments for. Defaults to current/next Monday.",
    )


class AssignmentPatch(BaseModel):
    """Schema for parent edits to a single assignment (reassign / reschedule / cancel)"""

    assigned_to: Optional[UUID] = Field(
        None, description="Move assignment to a different family member"
    )
    assigned_date: Optional[date] = Field(
        None, description="Move assignment to a different date (week_of recomputed)"
    )
    status: Optional[AssignmentStatus] = Field(
        None,
        description="Set status. Only 'cancelled' and 'pending' allowed here — use /complete to award points.",
    )


# Response schemas
class TaskAssignmentResponse(FamilyEntityResponse):
    """Schema for task assignment response"""

    template_id: UUID
    assigned_to: UUID
    status: AssignmentStatus
    assigned_date: date
    due_date: Optional[datetime] = None
    week_of: date
    completed_at: Optional[datetime] = None


class TaskAssignmentWithDetails(TaskAssignmentResponse):
    """Assignment response with template and user details"""

    template_title: str = ""
    template_description: Optional[str] = None
    template_title_es: Optional[str] = None
    template_description_es: Optional[str] = None
    template_points: int = 0
    template_is_bonus: bool = False
    assigned_user_name: str = ""
    is_overdue: bool = False
    can_complete: bool = True
    is_locked: bool = False
    approval_status: str = "none"
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None
    ai_validation_score: Optional[float] = None
    ai_validation_notes: Optional[str] = None
    approval_notes: Optional[str] = None


class ShuffleResponse(BaseModel):
    """Response from shuffle operation"""

    week_of: date
    assignments_created: int
    assignments: List[TaskAssignmentResponse]


class ShufflePreviewMemberTotal(BaseModel):
    user_id: UUID
    user_name: str
    points_this_week: int
    points_carry: int


class ShufflePreviewItem(BaseModel):
    template_id: UUID
    template_title: str
    template_title_es: Optional[str] = None
    template_points: int
    template_is_bonus: bool
    assigned_to: UUID
    assigned_user_name: str
    assigned_date: date
    week_of: date


class ShufflePreviewResponse(BaseModel):
    week_of: date
    totals_by_member: List[ShufflePreviewMemberTotal]
    assignments: List[ShufflePreviewItem]


class DailyProgressResponse(BaseModel):
    """Response showing today's progress for a user"""

    date: date
    required_total: int
    required_completed: int
    bonus_unlocked: bool
    bonus_total: int
    bonus_completed: int
    assignments: List[TaskAssignmentWithDetails]
    # Prior-day mandatory tasks still open (OVERDUE) that keep bonus/gigs
    # locked — surfaced so the kid can find and finish them.
    overdue_assignments: List[TaskAssignmentWithDetails] = []


class CompleteAssignmentRequest(BaseModel):
    """Schema for completing an assignment with optional proof."""
    proof_text: Optional[str] = Field(None, max_length=4000)
    proof_image_url: Optional[str] = Field(None, max_length=512)


class ApprovalDecision(BaseModel):
    approve: bool
    notes: Optional[str] = Field(None, max_length=2000)


class GigApprovalRow(BaseModel):
    assignment_id: UUID
    template_id: UUID
    template_title: str
    points: int
    assigned_to: UUID
    assigned_to_name: str
    completed_at: datetime
    proof_text: Optional[str] = None
    proof_image_url: Optional[str] = None
    ai_validation_score: Optional[float] = None
    ai_validation_notes: Optional[str] = None

    model_config = {"from_attributes": True}
