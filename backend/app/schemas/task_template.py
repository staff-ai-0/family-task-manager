"""
TaskTemplate Pydantic schemas

Request and response models for task template operations.
"""

from pydantic import BaseModel, Field
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


# Request schemas
class TaskTemplateCreate(TaskTemplateBase):
    """Schema for creating a new task template"""

    pass


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
