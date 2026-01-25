"""
Google OAuth Service

Handles Google OAuth authentication flow.
"""
from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from typing import Optional, Dict, Any
from uuid import UUID

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.family import Family
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


# Initialize OAuth
oauth = OAuth()

oauth.register(
    name='google',
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)


class GoogleOAuthService:
    """Service for Google OAuth operations"""
    
    @staticmethod
    async def get_authorization_url(request: Request, redirect_uri: str) -> str:
        """Get Google OAuth authorization URL"""
        return await oauth.google.authorize_redirect(request, redirect_uri)
    
    @staticmethod
    async def get_user_info(request: Request) -> Optional[Dict[str, Any]]:
        """Get user info from Google OAuth callback"""
        try:
            token = await oauth.google.authorize_access_token(request)
            user_info = token.get('userinfo')
            return user_info
        except Exception as e:
            print(f"Error getting user info from Google: {e}")
            return None
    
    @staticmethod
    async def find_or_create_user(
        db: AsyncSession,
        google_user_info: Dict[str, Any],
        family_id: Optional[UUID] = None
    ) -> Optional[User]:
        """Find existing user by OAuth ID or create new one"""
        from sqlalchemy import select
        
        google_id = google_user_info.get('sub')
        email = google_user_info.get('email')
        name = google_user_info.get('name')
        email_verified = google_user_info.get('email_verified', False)
        
        if not google_id or not email:
            return None
        
        # Try to find user by OAuth ID
        result = await db.execute(
            select(User).where(
                User.oauth_provider == 'google',
                User.oauth_id == google_id
            )
        )
        user = result.scalar_one_or_none()
        
        if user:
            return user
        
        # Try to find user by email
        result = await db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Link OAuth to existing account
            user.oauth_provider = 'google'
            user.oauth_id = google_id
            if email_verified and not user.email_verified:
                user.email_verified = True
                from datetime import datetime
                user.email_verified_at = datetime.utcnow()
            await db.commit()
            await db.refresh(user)
            return user
        
        # User doesn't exist - need family_id to create
        if not family_id:
            return None
        
        # Create new user
        user = User(
            email=email,
            name=name,
            password_hash=None,  # No password for OAuth users
            role=UserRole.PARENT,  # Default to parent for new OAuth users
            family_id=family_id,
            email_verified=email_verified,
            email_verified_at=None if not email_verified else __import__('datetime').datetime.utcnow(),
            oauth_provider='google',
            oauth_id=google_id
        )
        
        db.add(user)
        await db.commit()
        await db.refresh(user)
        
        return user
