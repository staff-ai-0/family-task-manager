"""
Authentication Service

Business logic for user authentication and authorization.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import Optional
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.models import User, Family
from app.models.user import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    UserRole,
)
from app.schemas.user import UserCreate, UserLogin
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token
from app.core.config import settings
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
    UnauthorizedException,
)


def pending_approval_message(lang: str | None) -> str:
    """Bilingual 'account pending parental approval' copy (403 detail)."""
    if (lang or "es") == "es":
        return (
            "Tu cuenta está pendiente de aprobación por un padre o madre "
            "de tu familia. Pídeles que la aprueben desde Miembros."
        )
    return (
        "Your account is pending parental approval. "
        "Ask a parent to approve it from the Members page."
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
    ) -> tuple[User, str, str]:
        """Authenticate user and return (user, access_token, refresh_token)."""
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

        # Join-code self-signups cannot log in until a parent approves.
        if getattr(user, "approval_status", APPROVAL_APPROVED) == APPROVAL_PENDING:
            raise ForbiddenException(
                pending_approval_message(user.preferred_lang)
            )

        # Create access + refresh tokens
        access_token = create_access_token(
            data={"sub": str(user.id), "family_id": str(user.family_id), "role": user.role.value}
        )
        refresh_token = create_refresh_token(str(user.id), version=user.token_version)

        return user, access_token, refresh_token

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
        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def deactivate_user(db: AsyncSession, user_id: UUID) -> User:
        """Deactivate a user account"""
        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def activate_user(db: AsyncSession, user_id: UUID) -> User:
        """Activate a user account"""
        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        
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

        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def approve_user(db: AsyncSession, user: User) -> User:
        """Approve a pending join-code member (parent action).

        Flips approval_status to 'approved' and stamps approved_at so the
        member can log in. Raises ValidationException when the account is
        not pending (approve is not a generic state toggle).
        """
        if user.approval_status != APPROVAL_PENDING:
            raise ValidationException("User is not pending approval")

        user.approval_status = APPROVAL_APPROVED
        user.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def notify_parents_of_pending_member(
        db: AsyncSession, new_user: User
    ) -> None:
        """In-app notify every active parent that a member awaits approval.

        Called after a join-code self-signup lands in 'pending'. Each parent
        gets the copy in their own preferred language with a link to the
        members page (where the Approve/Reject buttons live).
        """
        from app.services.notification_service import NotificationService

        parents = (
            (
                await db.execute(
                    select(User).where(
                        User.family_id == new_user.family_id,
                        User.role == UserRole.PARENT,
                        User.is_active == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        for parent in parents:
            await NotificationService.create_localized(
                db,
                family_id=new_user.family_id,
                key="member_pending_approval",
                user_id=parent.id,
                params={"name": new_user.name, "email": new_user.email},
                link="/parent/members",
                lang=parent.preferred_lang or "es",
            )

    @staticmethod
    async def delete_user(db: AsyncSession, user_id: UUID) -> None:
        """Permanently delete a user account
        
        This will cascade delete all related records (tasks, points, etc.)
        due to database foreign key constraints with CASCADE.
        """
        user = await AuthService.get_user_by_id(db, user_id)
        
        # Delete the user (cascade will handle related records)
        await db.delete(user)
        await db.commit()
