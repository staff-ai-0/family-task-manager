"""
User Pydantic schemas

Request and response models for user-related operations.
"""
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.models.user import UserRole


# Base schemas
class UserBase(BaseModel):
    """Base user schema with common fields"""
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=100)


# Request schemas
class UserCreate(UserBase):
    """Schema for creating a new user"""
    password: str = Field(..., min_length=8, max_length=100)
    role: UserRole = UserRole.CHILD
    family_id: UUID  # Required - must belong to a family


class UserUpdate(BaseModel):
    """Schema for updating user details"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserPasswordUpdate(BaseModel):
    """Schema for updating user password"""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=100)


# Response schemas
class UserResponse(UserBase):
    """Schema for user response"""
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    role: UserRole
    family_id: UUID
    points: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserWithStats(UserResponse):
    """User response with additional statistics"""
    total_tasks_completed: int = 0
    total_rewards_redeemed: int = 0
    active_consequences: int = 0
    pending_tasks: int = 0


# Login schemas
class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Schema for authentication token response"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
