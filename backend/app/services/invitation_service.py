"""
Family Invitation Service

Handles invitation creation, acceptance, and email notifications.
"""

from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.invitation import FamilyInvitation, InvitationStatus
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.core.exceptions import ValidationException, NotFoundException
from app.services.email_service import EmailService


class InvitationService:
    """Service for managing family invitations"""

    @staticmethod
    async def find_pending_for_email(
        db: AsyncSession, email: str
    ) -> "FamilyInvitation | None":
        """Return the newest still-valid PENDING invitation for an email.

        Case-insensitive on ``invited_email``. Used by the signup paths
        (Google OAuth + register-family) so a person who was invited by
        email joins the inviter's family instead of minting a new one when
        they sign up without clicking the emailed accept link.

        Returns None if there is no pending invitation, or the newest one is
        expired.
        """
        invitations = (await db.execute(
            select(FamilyInvitation).where(
                func.lower(FamilyInvitation.invited_email) == email.lower(),
                FamilyInvitation.status == InvitationStatus.PENDING,
            ).order_by(FamilyInvitation.created_at.desc())
        )).scalars().all()
        for invitation in invitations:
            if invitation.is_valid():
                return invitation
        return None

    @staticmethod
    def mark_accepted(invitation: "FamilyInvitation", user) -> None:
        """Stamp an invitation as accepted by ``user`` (shared by all accept
        paths — token accept, OAuth invite-join, register invite-join)."""
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(timezone.utc)
        invitation.accepted_by_user_id = user.id

    @staticmethod
    async def send_invitation(
        db: AsyncSession,
        family_id: UUID,
        invited_email: str,
        inviting_user: User,
        role: UserRole = UserRole.CHILD,
        base_url: str = ""
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
            role=role,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30)
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
        user_id: UUID = None,
        birthdate=None,
    ) -> tuple[FamilyInvitation, User]:
        """
        Accept a family invitation and create/update user account.

        Args:
            db: Database session
            invitation_code: The invitation code from the email
            user_name: User's name
            user_password: User's password
            user_id: Optional existing user ID to link to invitation
            birthdate: Optional date of birth (child/teen; no age gating yet)

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
            # An invitee who already has an account (e.g. registered
            # independently, creating their own family) must be MOVED into
            # the inviter's family — not INSERTed again, which would violate
            # the unique-email constraint and 400 the accept. Reconcile by
            # email before falling back to creating a fresh account.
            existing = (await db.execute(
                select(User).where(
                    func.lower(User.email) == invitation.invited_email.lower()
                )
            )).scalar_one_or_none()

            if existing is not None:
                existing.family_id = invitation.family_id
                user = existing
            else:
                # Create new user. Invitation-created accounts are
                # parent-vetted by construction (a parent sent the invite),
                # so approval_status stays at its 'approved' default.
                user = User(
                    email=invitation.invited_email,
                    name=user_name,
                    password_hash=get_password_hash(user_password),
                    role=invitation.role,  # Use role specified in invitation
                    family_id=invitation.family_id,
                    points=0,
                    is_active=True,
                    birthdate=birthdate,
                )
                db.add(user)
                await db.flush()

        # Mark invitation as accepted
        InvitationService.mark_accepted(invitation, user)
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
    async def resend_invitation(
        db: AsyncSession,
        invitation_id: UUID,
        family_id: UUID,
        base_url: str = "",
        fallback_user: User | None = None,
    ) -> FamilyInvitation:
        """
        Re-send the email for a pending invitation and refresh its expiry.

        Args:
            db: Database session
            invitation_id: Invitation to resend
            family_id: Family ID (authorization scope)
            base_url: Frontend origin for the acceptance link
            fallback_user: Used as the "invited by" sender if the original
                inviter can no longer be found

        Returns:
            The (expiry-refreshed) invitation

        Raises:
            NotFoundException: If invitation not found
            ValidationException: If invitation is not pending
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
            raise ValidationException("Only pending invitations can be resent")

        # Refresh the window so a stale-but-pending invite is valid again.
        invitation.expires_at = (
            datetime.now(timezone.utc) + timedelta(days=30)
        )
        await db.flush()

        inviter = (await db.execute(
            select(User).where(User.id == invitation.invited_by_user_id)
        )).scalar_one_or_none() or fallback_user

        if inviter is not None:
            await EmailService.send_invitation_email(
                db=db,
                invitation=invitation,
                inviting_user=inviter,
                base_url=base_url,
            )

        return invitation

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
