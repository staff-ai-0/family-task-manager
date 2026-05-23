"""
Family Pydantic schemas

Request and response models for family-related operations.
"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from uuid import UUID

from app.schemas.user import UserResponse
from app.schemas.base import EntityResponse


def _validate_iana_tz(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


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
    timezone: Optional[str] = Field(None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _check_tz(cls, v: Optional[str]) -> Optional[str]:
        return _validate_iana_tz(v)


# Response schemas
class FamilyResponse(EntityResponse):
    """Schema for family response"""

    name: str = Field(..., min_length=1, max_length=100)
    created_by: Optional[UUID] = None  # Optional for legacy data
    is_active: bool
    timezone: str = "UTC"


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
