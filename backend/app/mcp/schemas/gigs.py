"""MCP create/update schemas for the gigs domain (offerings + claims)."""

from typing import List, Optional
from pydantic import BaseModel


class OfferingCreate(BaseModel):
    title: str
    points: int
    difficulty: int = 1
    category: str = "other"
    description: Optional[str] = None
    allowed_roles: Optional[List[str]] = None


class OfferingUpdate(BaseModel):
    title: Optional[str] = None
    points: Optional[int] = None
    difficulty: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None
    allowed_roles: Optional[List[str]] = None
    is_active: Optional[bool] = None


class ClaimUpdate(BaseModel):
    """Parent-level patch on a gig claim (add notes, update proof text)."""
    proof_text: Optional[str] = None
    approval_notes: Optional[str] = None
