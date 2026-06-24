"""
MCP pydantic schemas for rewards-domain entities.

These are the MCP-facing create/update schemas — deliberately minimal
(no family_id, no read-only fields). The adapters translate these to the
real app service schemas before calling into the service layer.
"""
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── reward ─────────────────────────────────────────────────────────────────

class RewardCreate(BaseModel):
    """Schema for creating a reward via MCP."""
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points_cost: int = Field(..., ge=1, le=10000)
    category: str  # RewardCategory enum value as string
    icon: Optional[str] = Field(None, max_length=50)
    requires_parent_approval: bool = False
    is_default: bool = False


class RewardUpdate(BaseModel):
    """Schema for updating a reward via MCP."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points_cost: Optional[int] = Field(None, ge=1, le=10000)
    category: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    requires_parent_approval: Optional[bool] = None
    is_default: Optional[bool] = None


# ── redemption (create is a money-moving op) ──────────────────────────────

class RedemptionCreate(BaseModel):
    """Schema for redeeming a reward via MCP."""
    reward_id: UUID
    user_id: UUID
