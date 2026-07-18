"""
Family Pydantic schemas

Request and response models for family-related operations.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional, List
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
    # Parental opt-in for AI processing of kid-generated content (proof
    # photos, family chat). Service stamps ai_processing_consent_at on change.
    ai_processing_consent: Optional[bool] = None
    # User-visible term for the gig board, per family. DB/routes stay "gig".
    gig_term: Optional[Literal["gig", "chamba"]] = None

    @field_validator("timezone")
    @classmethod
    def _check_tz(cls, v: Optional[str]) -> Optional[str]:
        return _validate_iana_tz(v)


class FamilyDeleteRequest(BaseModel):
    """Re-auth payload for permanent family deletion (parent only).

    Password accounts must send ``password``. Google-only accounts (no
    password hash) must send ``confirm_name`` matching the family name.
    """

    password: Optional[str] = None
    confirm_name: Optional[str] = Field(None, max_length=100)


# Response schemas
class FamilyResponse(EntityResponse):
    """Schema for family response"""

    name: str = Field(..., min_length=1, max_length=100)
    created_by: Optional[UUID] = None  # Optional for legacy data
    is_active: bool
    timezone: str = "UTC"
    # AI opt-in state: consent_at is NULL until a parent decides either way
    # (dashboard shows a one-time prompt banner while NULL).
    ai_processing_consent: bool = False
    ai_processing_consent_at: Optional[datetime] = None
    # User-visible term for the gig board, per family. DB/routes stay "gig".
    gig_term: str = "gig"


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
