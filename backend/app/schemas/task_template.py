"""
TaskTemplate Pydantic schemas

Request and response models for task template operations.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID

from app.schemas.base import FamilyEntityResponse
from app.models.task_template import AssignmentType, GigMode


# Base schemas
class TaskTemplateBase(BaseModel):
    """Base task template schema with common fields"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    title_es: Optional[str] = Field(None, min_length=1, max_length=200)
    description_es: Optional[str] = Field(None, max_length=1000)
    points: int = Field(10, ge=0, le=1000)
    effort_level: int = Field(
        1,
        ge=1,
        le=3,
        description="Difficulty 1=easy (×1.0), 2=medium (×1.5), 3=hard (×2.0). Multiplies points on gig award.",
    )
    interval_days: int = Field(1, ge=1, le=7, description="1=daily, 3=every 3 days, 7=weekly")
    is_bonus: bool = False
    assignment_type: AssignmentType = AssignmentType.AUTO
    assigned_user_ids: Optional[List[UUID]] = Field(None, description="User UUIDs for FIXED or ROTATE assignment")
    allowed_roles: Optional[List[str]] = Field(
        None,
        description="Role strings (parent/teen/child) eligible under AUTO. Null/empty = all roles allowed.",
    )
    auto_late_penalty: bool = Field(
        False,
        description="Auto-apply a Consequence when this task flips PENDING → OVERDUE.",
    )
    late_restriction_type: Optional[str] = Field(
        None,
        description="RestrictionType value (screen_time, rewards, extra_tasks, allowance, activities, custom).",
    )
    late_severity: Optional[str] = Field(
        None, description="ConsequenceSeverity value (low, medium, high)."
    )
    late_duration_days: int = Field(1, ge=1, le=30)
    blocks_rewards: bool = Field(
        False,
        description="When True, an open assignment of this template blocks reward redemption.",
    )
    gig_mode: GigMode = Field(
        GigMode.CLAIM,
        description="Only used when is_bonus=True. claim|rotation|competition|collaboration.",
    )
    collaboration_min_count: int = Field(
        2,
        ge=2,
        le=10,
        description="When gig_mode=collaboration, minimum completers before points split.",
    )


# Request schemas
class TaskTemplateCreate(TaskTemplateBase):
    """Schema for creating a new task template.

    Both mandatory chores and gigs may carry points: a chore's points are
    privilege points awarded on completion; a gig's points are its peso value
    paid out as cash. (The old mandatory-must-be-zero rule was removed in the
    two-currency-economy change.)
    """


class TaskTemplateUpdate(BaseModel):
    """Schema for updating a task template"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    title_es: Optional[str] = Field(None, max_length=200)
    description_es: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, ge=0, le=1000)
    effort_level: Optional[int] = Field(None, ge=1, le=3)
    interval_days: Optional[int] = Field(None, ge=1, le=7)
    is_bonus: Optional[bool] = None
    is_active: Optional[bool] = None
    assignment_type: Optional[AssignmentType] = None
    assigned_user_ids: Optional[List[UUID]] = None
    allowed_roles: Optional[List[str]] = None
    auto_late_penalty: Optional[bool] = None
    late_restriction_type: Optional[str] = None
    late_severity: Optional[str] = None
    late_duration_days: Optional[int] = Field(None, ge=1, le=30)
    blocks_rewards: Optional[bool] = None
    gig_mode: Optional[GigMode] = None
    collaboration_min_count: Optional[int] = Field(None, ge=2, le=10)


# Response schemas
class TaskTemplateResponse(FamilyEntityResponse):
    """Schema for task template response"""

    title: str
    description: Optional[str] = None
    title_es: Optional[str] = None
    description_es: Optional[str] = None
    points: int
    effort_level: int = 1
    effective_points: int = 0
    interval_days: int
    is_bonus: bool
    is_active: bool
    created_by: Optional[UUID] = None
    assignment_type: AssignmentType
    assigned_user_ids: Optional[List[UUID]] = None
    allowed_roles: Optional[List[str]] = None
    auto_late_penalty: bool = False
    late_restriction_type: Optional[str] = None
    late_severity: Optional[str] = None
    late_duration_days: int = 1
    blocks_rewards: bool = False
    gig_mode: GigMode = GigMode.CLAIM
    collaboration_min_count: int = 2


class TaskTemplateWithStats(TaskTemplateResponse):
    """Task template response with assignment statistics"""

    assignment_count: int = 0
    completed_count: int = 0
    frequency_label: str = "daily"


class TranslateRequest(BaseModel):
    """Schema for requesting auto-translation of template fields"""

    source_lang: str = Field("en", pattern=r"^(en|es)$")
    target_lang: str = Field("es", pattern=r"^(en|es)$")


class TranslateTextRequest(BaseModel):
    """Schema for stateless translation of arbitrary title/description text.

    Unlike TranslateRequest (which re-reads a saved template's DB values), this
    carries the text to translate in the body — so the editor can translate
    in-progress edits before the first save, and the create flow can translate
    before the row exists. Nothing is persisted.
    """

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    source_lang: str = Field("en", pattern=r"^(en|es)$")
    target_lang: str = Field("es", pattern=r"^(en|es)$")


class TranslateResponse(BaseModel):
    """Schema for translation response"""

    title: str
    description: Optional[str] = None
    source_lang: str
    target_lang: str
