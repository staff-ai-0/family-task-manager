"""
TaskTemplate Pydantic schemas

Request and response models for task template operations.
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.schemas.base import FamilyEntityResponse


# Base schemas
class TaskTemplateBase(BaseModel):
    """Base task template schema with common fields"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: int = Field(10, ge=0, le=1000)
    interval_days: int = Field(1, ge=1, le=7, description="1=daily, 3=every 3 days, 7=weekly")
    is_bonus: bool = False


# Request schemas
class TaskTemplateCreate(TaskTemplateBase):
    """Schema for creating a new task template"""

    pass


class TaskTemplateUpdate(BaseModel):
    """Schema for updating a task template"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, ge=0, le=1000)
    interval_days: Optional[int] = Field(None, ge=1, le=7)
    is_bonus: Optional[bool] = None
    is_active: Optional[bool] = None


# Response schemas
class TaskTemplateResponse(FamilyEntityResponse):
    """Schema for task template response"""

    title: str
    description: Optional[str] = None
    points: int
    interval_days: int
    is_bonus: bool
    is_active: bool
    created_by: Optional[UUID] = None


class TaskTemplateWithStats(TaskTemplateResponse):
    """Task template response with assignment statistics"""

    assignment_count: int = 0
    completed_count: int = 0
    frequency_label: str = "daily"
