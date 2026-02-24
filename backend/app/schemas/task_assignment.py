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


class ShuffleResponse(BaseModel):
    """Response from shuffle operation"""

    week_of: date
    assignments_created: int
    assignments: List[TaskAssignmentResponse]


class DailyProgressResponse(BaseModel):
    """Response showing today's progress for a user"""

    date: date
    required_total: int
    required_completed: int
    bonus_unlocked: bool
    bonus_total: int
    bonus_completed: int
    assignments: List[TaskAssignmentWithDetails]
