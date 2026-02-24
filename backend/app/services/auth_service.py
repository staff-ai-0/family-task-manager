"""
Authentication Service

Business logic for user authentication and authorization.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.models import User, Family
from app.models.user import UserRole
from app.schemas.user import UserCreate, UserLogin
from app.core.security import verify_password, get_password_hash, create_access_token
from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
    UnauthorizedException,
)


class AuthService:
    """Service for authentication operations"""

    @staticmethod
    async def register_user(
        db: AsyncSession,
        user_data: UserCreate,
    ) -> User:
        """Register a new user"""
        # Check if email already exists
        existing_user = (await db.execute(
            select(User).where(User.email == user_data.email)
        )).scalar_one_or_none()
        
        if existing_user:
            raise ValidationException("Email already registered")
        
        # Verify family exists
        family = (await db.execute(
            select(Family).where(Family.id == user_data.family_id)
        )).scalar_one_or_none()
        
        if not family:
            raise NotFoundException("Family not found")
        
        # Create user
        user = User(
            email=user_data.email,
            name=user_data.name,
            password_hash=get_password_hash(user_data.password),
            role=user_data.role,
            family_id=user_data.family_id,
            points=0,
            is_active=True,
        )
        
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        login_data: UserLogin,
    ) -> tuple[User, str]:
        """Authenticate user and return user + access token"""
        # Find user by email
        user = (await db.execute(
            select(User).where(User.email == login_data.email)
        )).scalar_one_or_none()
        
        if not user:
            raise UnauthorizedException("Invalid email or password")
        
        # Verify password
        if not verify_password(login_data.password, user.password_hash):
            raise UnauthorizedException("Invalid email or password")
        
        # Check if user is active
        if not user.is_active:
            raise UnauthorizedException("Account is deactivated")
        
        # Create access token
        access_token = create_access_token(
            data={"sub": str(user.id), "family_id": str(user.family_id), "role": user.role.value}
        )
        
        return user, access_token

    @staticmethod
    async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User:
        """Get user by ID"""
        user = (await db.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if not user:
            raise NotFoundException("User not found")
        return user

    @staticmethod
    async def update_password(
        db: AsyncSession,
        user_id: UUID,
        current_password: str,
        new_password: str,
    ) -> User:
        """Update user password"""
        user = await AuthService.get_user_by_id(db, user_id)
        
        # Verify current password
        if not verify_password(current_password, user.password_hash):
            raise ValidationException("Current password is incorrect")
        
        # Update password
        user.password_hash = get_password_hash(new_password)
        user.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def deactivate_user(db: AsyncSession, user_id: UUID) -> User:
        """Deactivate a user account"""
        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = False
        user.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def activate_user(db: AsyncSession, user_id: UUID) -> User:
        """Activate a user account"""
        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = True
        user.updated_at = datetime.utcnow()
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def update_profile(db: AsyncSession, user_id: UUID, update_data: dict) -> User:
        """Update user profile fields (name, preferred_lang, etc.)"""
        user = await AuthService.get_user_by_id(db, user_id)

        for key, value in update_data.items():
            if value is not None and hasattr(user, key):
                setattr(user, key, value)

        user.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(user)
        return user
