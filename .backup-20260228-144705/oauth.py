"""
OAuth routes

Handles Google OAuth authentication.
"""

from fastapi import APIRouter, Depends, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional

from app.core.database import get_db
from app.services.google_oauth_service import GoogleOAuthService
from app.schemas.user import UserResponse, TokenResponse
from app.core.exceptions import ValidationException


router = APIRouter()


class GoogleTokenRequest(BaseModel):
    """Request model for Google OAuth token"""
    token: str = Field(..., description="Google ID token from frontend")
    family_id: Optional[str] = Field(None, description="Family ID for new user registration")
    join_code: Optional[str] = Field(None, description="Family join code to join an existing family")


@router.post("/google", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def google_oauth_login(
    request: GoogleTokenRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate with Google OAuth
    
    For existing users: Returns access token (join_code ignored)
    For new users with join_code: Joins existing family
    For new users without join_code: Creates new family
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # Verify Google token
    google_user_info = await GoogleOAuthService.verify_google_token(request.token)
    logger.info(f"Google OAuth login attempt: email={google_user_info.get('email')}, join_code={request.join_code}")
    
    # Authenticate or create user
    user, access_token, is_new_user = await GoogleOAuthService.authenticate_or_create_user(
        db, google_user_info, request.family_id, request.join_code
    )
    
    logger.info(f"Google OAuth successful: user_id={user.id}, email={user.email}, family_id={user.family_id}, is_new={is_new_user}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/google/verify", status_code=status.HTTP_200_OK)
async def verify_google_token(
    request: GoogleTokenRequest = Body(...),
):
    """
    Verify Google token and return user info without creating account
    
    Useful for checking if user exists before registration
    """
    google_user_info = await GoogleOAuthService.verify_google_token(request.token)
    
    return {
        "email": google_user_info["email"],
        "name": google_user_info["name"],
        "picture": google_user_info.get("picture"),
        "email_verified": google_user_info.get("email_verified", False),
    }
