"""
TaskTemplate Pydantic schemas

Request and response models for task template operations.
"""

from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from uuid import UUID

from app.schemas.base import FamilyEntityResponse
from app.models.task_template import AssignmentType


# Base schemas
class TaskTemplateBase(BaseModel):
    """Base task template schema with common fields"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    title_es: Optional[str] = Field(None, min_length=1, max_length=200)
    description_es: Optional[str] = Field(None, max_length=1000)
    points: int = Field(10, ge=0, le=1000)
    interval_days: int = Field(1, ge=1, le=7, description="1=daily, 3=every 3 days, 7=weekly")
    is_bonus: bool = False
    assignment_type: AssignmentType = AssignmentType.AUTO
    assigned_user_ids: Optional[List[UUID]] = Field(None, description="User UUIDs for FIXED or ROTATE assignment")
    allowed_roles: Optional[List[str]] = Field(
        None,
        description="Role strings (parent/teen/child) eligible under AUTO. Null/empty = all roles allowed.",
    )


# Request schemas
class TaskTemplateCreate(TaskTemplateBase):
    """Schema for creating a new task template"""

    @model_validator(mode="after")
    def _enforce_mandatory_zero_points(self):
        if not self.is_bonus and self.points != 0:
            raise ValueError(
                "Mandatory tasks (is_bonus=false) must have points=0. "
                "Set is_bonus=true to award points."
            )
        return self


class TaskTemplateUpdate(BaseModel):
    """Schema for updating a task template"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    title_es: Optional[str] = Field(None, max_length=200)
    description_es: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, ge=0, le=1000)
    interval_days: Optional[int] = Field(None, ge=1, le=7)
    is_bonus: Optional[bool] = None
    is_active: Optional[bool] = None
    assignment_type: Optional[AssignmentType] = None
    assigned_user_ids: Optional[List[UUID]] = None
    allowed_roles: Optional[List[str]] = None

    @model_validator(mode="after")
    def _enforce_mandatory_zero_points(self):
        # Only validate if both fields are present in the update; otherwise
        # we cannot know the combined state without the existing row.
        if self.is_bonus is False and self.points is not None and self.points != 0:
            raise ValueError(
                "Mandatory tasks (is_bonus=false) must have points=0."
            )
        return self


# Response schemas
class TaskTemplateResponse(FamilyEntityResponse):
    """Schema for task template response"""

    title: str
    description: Optional[str] = None
    title_es: Optional[str] = None
    description_es: Optional[str] = None
    points: int
    interval_days: int
    is_bonus: bool
    is_active: bool
    created_by: Optional[UUID] = None
    assignment_type: AssignmentType
    assigned_user_ids: Optional[List[UUID]] = None
    allowed_roles: Optional[List[str]] = None


class TaskTemplateWithStats(TaskTemplateResponse):
    """Task template response with assignment statistics"""

    assignment_count: int = 0
    completed_count: int = 0
    frequency_label: str = "daily"


class TranslateRequest(BaseModel):
    """Schema for requesting auto-translation of template fields"""

    source_lang: str = Field("en", pattern=r"^(en|es)$")
    target_lang: str = Field("es", pattern=r"^(en|es)$")


class TranslateResponse(BaseModel):
    """Schema for translation response"""

    title: str
    description: Optional[str] = None
    source_lang: str
    target_lang: str
