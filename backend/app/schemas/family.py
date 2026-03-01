"""
Family Pydantic schemas

Request and response models for family-related operations.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID

from app.schemas.user import UserResponse
from app.schemas.base import EntityResponse


# Base schemas
class FamilyBase(BaseModel):
    """Base family schema with common fields"""

    name: str = Field(..., min_length=1, max_length=100)


# Request schemas
class FamilyCreate(FamilyBase):
    """Schema for creating a new family"""

    pass


class FamilyUpdate(BaseModel):
    """Schema for updating family details"""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None


# Response schemas
class FamilyResponse(EntityResponse):
    """Schema for family response"""

    name: str = Field(..., min_length=1, max_length=100)
    created_by: Optional[UUID] = None  # Optional for legacy data
    is_active: bool


class FamilyWithMembers(FamilyResponse):
    """Family response with member list"""

    members: List[UserResponse] = []


class FamilyStats(BaseModel):
    """Family statistics"""

    total_members: int
    total_tasks: int
    completed_tasks: int
    pending_tasks: int
    total_rewards: int
    active_consequences: int
