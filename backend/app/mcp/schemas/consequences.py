"""MCP pydantic schemas for the consequences domain.

Deliberately minimal — no family_id (stripped by dispatch), no read-only
fields. The adapter translates to the real app ConsequenceCreate/Update
schemas before calling the service.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConsequenceCreate(BaseModel):
    """Schema for creating a consequence via MCP."""
    title: str = Field(..., min_length=1, max_length=200)
    applied_to_user: UUID
    restriction_type: str  # RestrictionType enum value as string
    severity: str = "low"  # ConsequenceSeverity enum value as string
    duration_days: int = Field(1, ge=1, le=30)
    description: Optional[str] = None


class ConsequenceUpdate(BaseModel):
    """Schema for updating a consequence via MCP."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    severity: Optional[str] = None
    restriction_type: Optional[str] = None
    duration_days: Optional[int] = Field(None, ge=1, le=30)
