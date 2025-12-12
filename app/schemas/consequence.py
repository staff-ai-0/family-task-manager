"""
Consequence Pydantic schemas

Request and response models for consequence-related operations.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.models.consequence import ConsequenceSeverity, RestrictionType


# Base schemas
class ConsequenceBase(BaseModel):
    """Base consequence schema with common fields"""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    severity: ConsequenceSeverity = ConsequenceSeverity.LOW
    restriction_type: RestrictionType
    duration_days: int = Field(1, ge=1, le=30)


# Request schemas
class ConsequenceCreate(ConsequenceBase):
    """Schema for creating a new consequence"""
    applied_to_user: UUID
    triggered_by_task_id: Optional[UUID] = None


class ConsequenceUpdate(BaseModel):
    """Schema for updating consequence details"""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    severity: Optional[ConsequenceSeverity] = None
    restriction_type: Optional[RestrictionType] = None
    duration_days: Optional[int] = Field(None, ge=1, le=30)


class ConsequenceResolve(BaseModel):
    """Schema for resolving a consequence"""
    resolved_by: UUID
    resolution_notes: Optional[str] = None


# Response schemas
class ConsequenceResponse(ConsequenceBase):
    """Schema for consequence response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    active: bool
    resolved: bool
    triggered_by_task_id: Optional[UUID]
    applied_to_user: UUID
    family_id: UUID
    start_date: datetime
    end_date: datetime
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ConsequenceWithDetails(ConsequenceResponse):
    """Consequence response with additional details"""
    user_name: Optional[str] = None
    task_title: Optional[str] = None
    is_expired: bool = False
    days_remaining: int = 0
