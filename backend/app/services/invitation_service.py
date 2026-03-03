"""
Family Invitation Service

Handles invitation creation, acceptance, and email notifications.
"""

from uuid import UUID
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.user import User, UserRole
from app.core.security import get_password_hash, create_access_token
from app.core.exceptions import ValidationException, NotFoundException
from app.services.email_service import EmailService


class InvitationService:
    """Service for managing family invitations"""

    @staticmethod
    async def send_invitation(
        db: AsyncSession,
        family_id: UUID,
        invited_email: str,
        inviting_user: User,
        base_url: str = "https://family.agent-ia.mx"
    ) -> FamilyInvitation:
        """
        Send a family invitation to an email address.
        
        Args:
            db: Database session
            family_id: Family to invite to
            invited_email: Email to invite
            inviting_user: User sending the invitation
            base_url: Base URL for the invitation link
            
        Returns:
            FamilyInvitation object
            
        Raises:
            ValidationException: If email is already a family member or invalid
        """
        # Check if email is already a member of the family
        existing = (await db.execute(
            select(User).where(
                User.email == invited_email,
                User.family_id == family_id
            )
        )).scalar_one_or_none()
        
        if existing:
            raise ValidationException(f"{invited_email} is already a family member")

        # Check if there's already a pending invitation for this email
        pending = (await db.execute(
            select(FamilyInvitation).where(
                FamilyInvitation.invited_email == invited_email,
                FamilyInvitation.family_id == family_id,
                FamilyInvitation.status == InvitationStatus.PENDING
            )
        )).scalar_one_or_none()

        if pending and not pending.is_expired():
            raise ValidationException(
                f"An active invitation is already pending for {invited_email}"
            )

        # Create invitation
        invitation_code = FamilyInvitation.generate_code()
        invitation = FamilyInvitation(
            family_id=family_id,
            invited_email=invited_email,
            invited_by_user_id=inviting_user.id,
            invitation_code=invitation_code,
            status=InvitationStatus.PENDING,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        
        db.add(invitation)
        await db.flush()

        # Send invitation email
        await EmailService.send_invitation_email(
            db=db,
            invitation=invitation,
            inviting_user=inviting_user,
            base_url=base_url
        )

        return invitation

    @staticmethod
    async def accept_invitation(
        db: AsyncSession,
        invitation_code: str,
        user_name: str,
        user_password: str,
        user_id: UUID = None
    ) -> tuple[FamilyInvitation, User]:
        """
        Accept a family invitation and create/update user account.
        
        Args:
            db: Database session
            invitation_code: The invitation code from the email
            user_name: User's name
            user_password: User's password
            user_id: Optional existing user ID to link to invitation
            
        Returns:
            Tuple of (invitation, user)
            
        Raises:
            NotFoundException: If invitation not found
            ValidationException: If invitation is not valid
        """
        invitation = (await db.execute(
            select(FamilyInvitation).where(
                FamilyInvitation.invitation_code == invitation_code
            )
        )).scalar_one_or_none()

        if not invitation:
            raise NotFoundException("Invitation not found")

        if not invitation.is_valid():
            if invitation.is_expired():
                invitation.status = InvitationStatus.EXPIRED
                await db.flush()
            raise ValidationException("Invitation is no longer valid")

        # Create new user if needed, or update existing
        if user_id:
            # Link existing user to invitation
            user = (await db.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            
            if not user:
                raise NotFoundException("User not found")
            
            user.family_id = invitation.family_id
        else:
            # Create new user
            user = User(
                email=invitation.invited_email,
                name=user_name,
                password_hash=get_password_hash(user_password),
                role=UserRole.CHILD,  # Default role for invited members
                family_id=invitation.family_id,
                points=0,
                is_active=True,
            )
            db.add(user)
            await db.flush()

        # Mark invitation as accepted
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.utcnow()
        invitation.accepted_by_user_id = user.id
        await db.flush()

        return invitation, user

    @staticmethod
    async def get_pending_invitations(
        db: AsyncSession,
        family_id: UUID
    ) -> list[FamilyInvitation]:
        """
        Get all pending invitations for a family.
        
        Args:
            db: Database session
            family_id: Family ID
            
        Returns:
            List of pending invitations
        """
        invitations = (await db.execute(
            select(FamilyInvitation).where(
                FamilyInvitation.family_id == family_id,
                FamilyInvitation.status == InvitationStatus.PENDING
            ).order_by(FamilyInvitation.created_at.desc())
        )).scalars().all()

        return invitations

    @staticmethod
    async def cancel_invitation(
        db: AsyncSession,
        invitation_id: UUID,
        family_id: UUID
    ) -> FamilyInvitation:
        """
        Cancel a pending invitation.
        
        Args:
            db: Database session
            invitation_id: Invitation ID to cancel
            family_id: Family ID (for authorization check)
            
        Returns:
            Updated invitation
            
        Raises:
            NotFoundException: If invitation not found
            ValidationException: If invitation cannot be cancelled
        """
        invitation = (await db.execute(
            select(FamilyInvitation).where(
                FamilyInvitation.id == invitation_id,
                FamilyInvitation.family_id == family_id
            )
        )).scalar_one_or_none()

        if not invitation:
            raise NotFoundException("Invitation not found")

        if invitation.status != InvitationStatus.PENDING:
            raise ValidationException("Only pending invitations can be cancelled")

        invitation.status = InvitationStatus.REJECTED
        await db.flush()

        return invitation
