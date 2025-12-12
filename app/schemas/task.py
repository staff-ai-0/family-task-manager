"""
Task Pydantic schemas

Request and response models for task-related operations.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.models.task import TaskStatus, TaskFrequency


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
class TaskResponse(TaskBase):
    """Schema for task response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    status: TaskStatus
    assigned_to: UUID
    created_by: Optional[UUID]
    family_id: UUID
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    consequence_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class TaskWithDetails(TaskResponse):
    """Task response with additional details"""
    assigned_user_name: Optional[str] = None
    created_by_name: Optional[str] = None
    is_overdue: bool = False
    can_complete: bool = True
