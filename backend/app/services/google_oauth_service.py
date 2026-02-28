"""
Google OAuth Service

Handles Google OAuth authentication flow.
"""
from google.oauth2 import id_token
from google.auth.transport import requests
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, Dict, Any
from uuid import uuid4

from app.models import User, Family
from app.models.user import UserRole
from app.core.config import settings
from app.core.security import create_access_token
from app.core.exceptions import (
    ValidationException,
    UnauthorizedException,
    NotFoundException,
)
from app.services.family_service import FamilyService


class GoogleOAuthService:
    """Service for Google OAuth operations"""

    @staticmethod
    async def verify_google_token(token: str) -> Dict[str, Any]:
        """
        Verify Google ID token and return user info
        
        Args:
            token: Google ID token from frontend
            
        Returns:
            Dict with user info (sub, email, name, picture)
            
        Raises:
            UnauthorizedException: If token is invalid
        """
        try:
            idinfo = id_token.verify_oauth2_token(
                token, 
                requests.Request(), 
                settings.GOOGLE_CLIENT_ID
            )
            
            # Verify the issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Wrong issuer.')
            
            return {
                'google_id': idinfo['sub'],
                'email': idinfo['email'],
                'name': idinfo.get('name', ''),
                'picture': idinfo.get('picture', ''),
                'email_verified': idinfo.get('email_verified', False),
            }
        except ValueError as e:
            raise UnauthorizedException(f"Invalid Google token: {str(e)}")

    @staticmethod
    async def authenticate_or_create_user(
        db: AsyncSession,
        google_user_info: Dict[str, Any],
        family_id: Optional[str] = None,
        join_code: Optional[str] = None,
    ) -> tuple[User, str, bool]:
        """
        Authenticate existing user or create new user from Google OAuth
        
        Args:
            db: Database session
            google_user_info: User info from Google
            family_id: Optional family ID for new user registration
            join_code: Optional family join code to join an existing family
            
        Returns:
            Tuple of (User, access_token, is_new_user)
        """
        google_id = google_user_info['google_id']
        email = google_user_info['email']
        
        # Try to find existing user by OAuth ID
        user = (await db.execute(
            select(User).where(User.oauth_id == google_id, User.oauth_provider == "google")
        )).scalar_one_or_none()
        
        # If not found by OAuth ID, try by email
        if not user:
            user = (await db.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            
            # If found by email, link the Google account
            if user:
                user.oauth_provider = "google"
                user.oauth_id = google_id
                if google_user_info.get('email_verified'):
                    user.email_verified = True
                await db.commit()
                await db.refresh(user)
        
        # If user exists, authenticate
        if user:
            if not user.is_active:
                raise UnauthorizedException("Account is deactivated")
            
            access_token = create_access_token(
                data={
                    "sub": str(user.id),
                    "family_id": str(user.family_id),
                    "role": user.role.value
                }
            )
            return user, access_token, False
        
        # New user - determine which family to join
        target_family_id = None
        
        # Priority 1: Join code (join existing family)
        if join_code:
            family = await FamilyService.get_family_by_join_code(db, join_code)
            if not family:
                raise ValidationException("Invalid join code. Ask your family admin for the correct code.")
            target_family_id = family.id
        
        # Priority 2: Explicit family_id
        elif family_id:
            family = (await db.execute(
                select(Family).where(Family.id == family_id)
            )).scalar_one_or_none()
            
            if not family:
                raise NotFoundException("Family not found")
            
            target_family_id = family.id
        
        # Priority 3: Auto-create a new family
        else:
            user_name = google_user_info.get('name', email.split('@')[0])
            family = Family(
                id=uuid4(),
                name=f"{user_name}'s Family",
            )
            db.add(family)
            await db.flush()
            target_family_id = family.id
        
        # Create new user
        user = User(
            id=uuid4(),
            email=email,
            name=google_user_info.get('name', email.split('@')[0]),
            password_hash=None,  # No password for OAuth users
            oauth_provider="google",
            oauth_id=google_id,
            role=UserRole.PARENT,  # Default role for new OAuth users
            family_id=target_family_id,
            points=0,
            is_active=True,
            email_verified=google_user_info.get('email_verified', False),
        )
        
        db.add(user)
        await db.flush()
        
        # Set created_by on family if we just created it
        if not family_id and not join_code and family:
            family.created_by = user.id
        
        await db.commit()
        await db.refresh(user)
        
        # Create access token
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "family_id": str(user.family_id),
                "role": user.role.value
            }
        )
        
        return user, access_token, True
