"""
Base Pydantic schemas for consistent response structure.
Reduces duplication across all schema files.
"""

from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID


class TimestampMixin(BaseModel):
    """Mixin for created_at/updated_at timestamps"""

    created_at: datetime
    updated_at: datetime


class BaseResponse(BaseModel):
    """Base response schema with ORM configuration"""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=False,
        str_strip_whitespace=True,
    )


class EntityResponse(BaseResponse, TimestampMixin):
    """
    Base for entity responses with ID and timestamps.
    Use for any entity that has id, created_at, updated_at.
    """

    id: UUID


class FamilyEntityResponse(EntityResponse):
    """
    Base for family-scoped entity responses.
    Use for entities that belong to a family.
    """

    family_id: UUID


class TitleDescriptionMixin(BaseModel):
    """Mixin for entities with title and description fields"""

    title: str
    description: str | None = None


class MessageResponse(BaseModel):
    """Standard message response"""

    message: str
    success: bool = True
