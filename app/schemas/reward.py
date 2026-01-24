"""
Reward Pydantic schemas

Request and response models for reward-related operations.
"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

from app.models.reward import RewardCategory
from app.schemas.base import FamilyEntityResponse


# Base schemas
class RewardBase(BaseModel):
    """Base reward schema with common fields"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points_cost: int = Field(..., ge=1, le=10000)
    category: RewardCategory
    icon: Optional[str] = Field(None, max_length=50)


# Request schemas
class RewardCreate(RewardBase):
    """Schema for creating a new reward"""

    requires_parent_approval: bool = False


class RewardUpdate(BaseModel):
    """Schema for updating reward details"""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points_cost: Optional[int] = Field(None, ge=1, le=10000)
    category: Optional[RewardCategory] = None
    icon: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None
    requires_parent_approval: Optional[bool] = None


class RewardRedeem(BaseModel):
    """Schema for redeeming a reward"""

    user_id: UUID


class RewardRedeemApproval(BaseModel):
    """Schema for parent approval of reward redemption"""

    approved: bool
    approved_by: UUID
    notes: Optional[str] = None


# Response schemas
class RewardResponse(FamilyEntityResponse):
    """Schema for reward response"""

    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    points_cost: int = Field(..., ge=1, le=10000)
    category: RewardCategory
    icon: Optional[str] = Field(None, max_length=50)
    is_active: bool
    requires_parent_approval: bool


class RewardWithStatus(RewardResponse):
    """Reward response with user-specific status"""

    can_afford: bool = False  # User has enough points
    is_redeemable: bool = True  # Active and available
    times_redeemed: int = 0  # How many times user redeemed this
