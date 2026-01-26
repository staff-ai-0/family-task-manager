"""
Task Pydantic schemas

Request and response models for task-related operations.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID

from app.models.task import TaskStatus, TaskFrequency
from app.schemas.base import FamilyEntityResponse


# Base schemas
class TaskBase(BaseModel):
    """Base task schema with common fields"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: int = Field(10, ge=0, le=1000)
    is_default: bool = False
    frequency: TaskFrequency = TaskFrequency.DAILY


# Request schemas
class TaskCreate(TaskBase):
    """Schema for creating a new task"""

    assigned_to: UUID
    due_date: Optional[datetime] = None


class TaskUpdate(BaseModel):
    """Schema for updating task details"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: Optional[int] = Field(None, ge=0, le=1000)
    is_default: Optional[bool] = None
    frequency: Optional[TaskFrequency] = None
    assigned_to: Optional[UUID] = None
    due_date: Optional[datetime] = None
    status: Optional[TaskStatus] = None


class TaskComplete(BaseModel):
    """Schema for marking task as completed"""

    completed_by: UUID  # User who completed the task


# Response schemas
class TaskResponse(FamilyEntityResponse):
    """Schema for task response"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points: int = Field(10, ge=0, le=1000)
    is_default: bool = False
    frequency: TaskFrequency = TaskFrequency.DAILY
    status: TaskStatus
    assigned_to: UUID
    created_by: Optional[UUID]
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    consequence_id: Optional[UUID] = None


class TaskWithDetails(TaskResponse):
    """Task response with additional details"""

    assigned_user_name: Optional[str] = None
    created_by_name: Optional[str] = None
    is_overdue: bool = False
    can_complete: bool = True


# Bulk operation schemas
class TaskBulkCreate(TaskBase):
    """Schema for creating tasks for multiple users at once"""

    assigned_to: List[UUID] = Field(..., min_length=1, description="List of user IDs to assign the task to")
    due_date: Optional[datetime] = None


class TaskBulkCreateResponse(BaseModel):
    """Response for bulk task creation"""

    created_count: int
    tasks: List[TaskResponse]


class TaskDuplicate(BaseModel):
    """Schema for duplicating a task"""

    assigned_to: Optional[UUID] = Field(None, description="New user to assign the duplicated task to (optional)")
    include_due_date: bool = Field(False, description="Whether to copy the due date")


class TaskRegenerateRequest(BaseModel):
    """Schema for regenerating recurring tasks"""

    frequency: TaskFrequency = Field(..., description="Frequency of tasks to regenerate")
    user_ids: Optional[List[UUID]] = Field(None, description="Specific users to regenerate tasks for (optional, defaults to all)")
    reset_completed: bool = Field(True, description="Whether to reset completed tasks of this frequency")
