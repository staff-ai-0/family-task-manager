"""
Family Invitation Schemas

Request and response models for family invitation operations.
"""

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from uuid import UUID
from typing import Optional
from app.models.user import UserRole


class SendFamilyInvitationRequest(BaseModel):
    """Request to send a family invitation"""
    email: EmailStr = Field(..., description="Email address to invite")
    family_id: str = Field(..., description="Family ID to invite to")
    role: UserRole = Field(default=UserRole.CHILD, description="Role for the invited user")
    message: Optional[str] = Field(None, description="Optional custom message")


class InvitationResponse(BaseModel):
    """Response with invitation details"""
    id: UUID
    family_id: UUID
    invited_email: str
    status: str
    role: str
    created_at: datetime
    expires_at: datetime
    invitation_code: str
    accepted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AcceptInvitationRequest(BaseModel):
    """Request to accept a family invitation"""
    invitation_code: str = Field(..., description="The invitation code from the email")
    password: str = Field(..., min_length=8, description="Password for new user account")
    name: str = Field(..., max_length=100, description="User's full name")


class AcceptInvitationResponse(BaseModel):
    """Response after accepting invitation"""
    success: bool
    access_token: str
    token_type: str
    message: str


class PendingInvitationResponse(BaseModel):
    """Response with pending invitations for current family"""
    id: UUID
    invited_email: str
    status: str
    role: str
    created_at: datetime
    expires_at: datetime
    invited_by_user_name: str

    class Config:
        from_attributes = True
