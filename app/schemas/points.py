"""
PointTransaction Pydantic schemas

Request and response models for point transaction operations.
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.models.point_transaction import TransactionType


# Base schemas
class PointTransactionBase(BaseModel):
    """Base point transaction schema"""
    type: TransactionType
    points: int
    description: Optional[str] = None


# Request schemas
class PointTransactionCreate(PointTransactionBase):
    """Schema for creating a manual point transaction"""
    user_id: UUID
    created_by: UUID


class ParentAdjustment(BaseModel):
    """Schema for parent making manual point adjustment"""
    user_id: UUID
    points: int = Field(..., ge=-1000, le=1000)  # Limit adjustment range
    reason: str = Field(..., min_length=1, max_length=500)


class PointTransfer(BaseModel):
    """Schema for transferring points between users"""
    from_user_id: UUID
    to_user_id: UUID
    points: int = Field(..., ge=1, le=1000)
    reason: Optional[str] = Field(None, max_length=500)


# Response schemas
class PointTransactionResponse(PointTransactionBase):
    """Schema for point transaction response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    user_id: UUID
    balance_before: int
    balance_after: int
    task_id: Optional[UUID]
    reward_id: Optional[UUID]
    created_by: Optional[UUID]
    created_at: datetime


class PointTransactionWithDetails(PointTransactionResponse):
    """Point transaction with additional details"""
    user_name: Optional[str] = None
    task_title: Optional[str] = None
    reward_title: Optional[str] = None
    created_by_name: Optional[str] = None


# Summary schemas
class PointsSummary(BaseModel):
    """Summary of user points and recent transactions"""
    user_id: UUID
    current_balance: int
    total_earned: int
    total_spent: int
    recent_transactions: list[PointTransactionResponse] = []
