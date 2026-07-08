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
from app.core.security import create_access_token, create_refresh_token
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
        Verify Google ID token and return user info.

        Accepts tokens from any of the client IDs in settings.google_accepted_audiences
        (Web client + any configured mobile/desktop clients registered under
        the same Google Cloud project). Google's library will only validate
        one audience per call, so we verify without an audience constraint
        and then check aud against our allow-list manually.

        Args:
            token: Google ID token from frontend (Web or mobile)

        Returns:
            Dict with user info (sub, email, name, picture)

        Raises:
            UnauthorizedException: If token is invalid, signature check fails,
                issuer is wrong, or aud is not in the allow-list.
        """
        accepted = settings.google_accepted_audiences
        if not accepted:
            # Misconfiguration: refuse to accept any token rather than a
            # silent security downgrade that would trust every Google-issued
            # token in the world.
            raise UnauthorizedException(
                "No Google client IDs configured on the server"
            )

        try:
            # audience=None → library skips the aud check; we do it below
            # against our multi-client allow-list. Signature, expiration,
            # and issuer checks still run as normal.
            idinfo = id_token.verify_oauth2_token(
                token,
                requests.Request(),
                audience=None,
            )

            # Issuer check (library also does this but we re-assert)
            if idinfo.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
                raise ValueError(f"Wrong issuer: {idinfo.get('iss')!r}")

            aud = idinfo.get('aud')
            if aud not in accepted:
                raise ValueError(
                    f"Token has wrong audience {aud}, expected one of {accepted}"
                )

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
        role: Optional[str] = None,
        accept_terms: bool = False,
    ) -> tuple[User, str, str, bool]:
        """
        Authenticate existing user or create new user from Google OAuth

        Args:
            db: Database session
            google_user_info: User info from Google
            family_id: Optional family ID for new user registration
            join_code: Optional family join code to join an existing family
            role: Requested role when joining via join_code (child/teen);
                joining defaults to CHILD and never grants PARENT — founding
                a new family (no join_code/family_id) is always PARENT
            accept_terms: Terms + privacy-notice consent. REQUIRED (true)
                when the signup founds a NEW family; recorded (consented_at
                + policy version) whenever true.

        Returns:
            Tuple of (User, access_token, refresh_token, is_new_user)

        Raises:
            ForbiddenException: When the account is (or just became) PENDING
                parental approval — join-code/family_id self-signups get NO
                tokens until a parent approves from the members page. The
                account IS created before this is raised.
            ValidationException: New-family signup without accept_terms, or
                an invalid join code.
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

            # Pending join-code signups must not bypass parental approval by
            # signing in with Google using the same email.
            from app.models.user import APPROVAL_PENDING
            from app.services.auth_service import pending_approval_message
            from app.core.exceptions import ForbiddenException
            if getattr(user, "approval_status", None) == APPROVAL_PENDING:
                raise ForbiddenException(
                    pending_approval_message(user.preferred_lang)
                )

            access_token = create_access_token(
                data={
                    "sub": str(user.id),
                    "family_id": str(user.family_id),
                    "role": user.role.value
                }
            )
            refresh_token = create_refresh_token(str(user.id), version=user.token_version)
            return user, access_token, refresh_token, False
        
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
            # Founding an account/family requires explicit consent to the
            # terms + privacy notice (LFPDPPP) — same rule as
            # POST /api/auth/register-family. Bilingual because this
            # unauthenticated request carries no language preference.
            if not accept_terms:
                raise ValidationException(
                    "Debes aceptar los Términos y el Aviso de Privacidad "
                    "para crear tu cuenta. / You must accept the Terms and "
                    "the Privacy Notice to create your account."
                )

            user_name = google_user_info.get('name', email.split('@')[0])
            family = Family(
                id=uuid4(),
                name=f"{user_name}'s Family",
            )
            db.add(family)
            await db.flush()
            target_family_id = family.id

        # Role selection is deliberately narrow to prevent privilege escalation.
        # This route is UNAUTHENTICATED, so nothing in the payload is trusted:
        #  - join_code: shared with kids, so it must never mint a PARENT.
        #    The requested role is capped at TEEN (a requested "parent" is
        #    demoted to CHILD) — same policy as /api/auth/register-family.
        #  - family_id: NOT even a secret — it appears in every
        #    UserResponse/JWT, so any member could POST it with a fresh
        #    Google token. Force CHILD regardless of the requested role.
        #  - neither: auto-creating a brand-new family makes the founder
        #    PARENT (consent enforced above).
        # Real parent additions go through the invitation flow (role set server-side).
        if join_code:
            new_role = UserRole(role) if role in ("teen", "child") else UserRole.CHILD
        elif family_id:
            new_role = UserRole.CHILD
        else:
            new_role = UserRole.PARENT

        from datetime import datetime, timezone

        from app.models.user import (
            APPROVAL_APPROVED,
            APPROVAL_PENDING,
            CONSENT_POLICY_VERSION,
        )

        # Any self-signup into an EXISTING family (join_code or family_id)
        # starts PENDING parental approval — no tokens until a parent
        # approves from the members page. Founding a new family is trusted
        # (the founder just consented above).
        joining_existing_family = bool(join_code or family_id)
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        user = User(
            id=uuid4(),
            email=email,
            name=google_user_info.get('name', email.split('@')[0]),
            password_hash=None,  # No password for OAuth users
            oauth_provider="google",
            oauth_id=google_id,
            role=new_role,
            family_id=target_family_id,
            points=0,
            is_active=True,
            email_verified=google_user_info.get('email_verified', False),
            approval_status=(
                APPROVAL_PENDING if joining_existing_family else APPROVAL_APPROVED
            ),
            approved_at=None if joining_existing_family else now,
            # Record consent whenever it was given (required for founders).
            consented_at=now if accept_terms else None,
            consent_policy_version=CONSENT_POLICY_VERSION if accept_terms else None,
        )

        db.add(user)
        await db.flush()

        # Set created_by on family if we just created it
        if not family_id and not join_code and family:
            family.created_by = user.id

        await db.commit()
        await db.refresh(user)

        # Pending self-signups get NO tokens — a parent must approve them
        # first. Notify the family's parents in-app (same flow as the
        # register-family join-code path), then surface the pending state
        # as a 403 with the bilingual wait-for-parent copy. NB: the account
        # was committed above on purpose; retrying "Sign in with Google"
        # lands in the existing-user pending block and gets the same 403.
        if user.approval_status == APPROVAL_PENDING:
            from app.services.auth_service import (
                AuthService,
                pending_approval_message,
            )
            from app.core.exceptions import ForbiddenException

            try:
                await AuthService.notify_parents_of_pending_member(db, user)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "pending-member parent notification failed (OAuth signup)",
                    exc_info=True,
                )
            raise ForbiddenException(
                pending_approval_message(user.preferred_lang)
            )

        # Create access + refresh tokens
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "family_id": str(user.family_id),
                "role": user.role.value
            }
        )
        refresh_token = create_refresh_token(str(user.id), version=user.token_version)

        # Fire welcome email for this brand-new Google user. Google has
        # already vouched for email ownership (email_verified=true in
        # the ID token), so no verification step gates the welcome —
        # we send it right at account-creation time. Idempotent and
        # fire-and-forget: a failure here must never block the OAuth
        # sign-in flow returning a valid token to the frontend.
        try:
            from app.services.email_service import EmailService
            await EmailService.send_welcome_if_not_sent(
                db=db, user=user, base_url=settings.email_link_base
            )
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                f"welcome dispatch after OAuth signup failed for {user.email}",
                exc_info=True,
            )

        return user, access_token, refresh_token, True
