"""
Authentication Service

Business logic for user authentication and authorization.
"""
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from uuid import UUID

from app.models import User, Family
from app.models.family import generate_join_code
from app.models.user import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    UserRole,
)
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    RegisterFamilyRequest,
    RegisterFamilyResponse,
)
from app.core.config import settings
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
    UnauthorizedException,
)
from app.services.email_service import EmailService
from app.services.invitation_service import InvitationService


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
    async def register_family(
        db: AsyncSession,
        data: RegisterFamilyRequest,
    ) -> RegisterFamilyResponse:
        """Create a new family + founding PARENT user, or join existing family.

        - If family_code is provided: join the existing family with that code,
          as the requested role (child/teen) — defaults to CHILD. Parents can
          promote members later from the members page.
        - If family_code is not provided: create a new family using family_name;
          the founder is always PARENT.

        Consent + approval rules (2026-07-07 compliance):
        - Founding a new family REQUIRES accept_terms=true (terms + privacy
          notice); the acceptance timestamp and policy version are stored.
        - Joining by code never grants PARENT (capped at TEEN) and the account
          starts PENDING parental approval: no tokens are issued and login is
          blocked until a parent approves from the members page.

        Raises `fastapi.HTTPException` directly (not the domain-exception
        convention) — this is the route's long-standing contract with the
        frontend/mobile clients, preserved as-is when this was extracted out
        of the route handler.
        """
        lang = "es" if (data.preferred_lang or "es") == "es" else "en"

        # Check email not already taken
        existing = (await db.execute(
            select(User).where(User.email == data.email)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        from datetime import datetime, timezone

        from app.models.user import (
            APPROVAL_APPROVED,
            APPROVAL_PENDING,
            CONSENT_POLICY_VERSION,
            UserRole as UR,
        )

        # Determine which family to use
        pending_invite = None
        if data.family_code:
            # Join existing family by code
            family_code = data.family_code.strip().upper()
            family = (await db.execute(
                select(Family).where(
                    Family.join_code == family_code,
                    Family.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

            if not family:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Family code not found. Please check the code and try again.",
                )

            if not family.is_active:
                raise HTTPException(
                    status_code=status.HTTP_410_GONE,
                    detail="This family is no longer active.",
                )

            # Enforce the plan's family_member limit — the same cap the
            # invitation path applies (invitations.py). Without this, anyone
            # holding the join code could grow the family past its plan limit.
            from sqlalchemy import func as sa_func
            from app.core.premium import (
                DEFAULT_FREE_LIMITS,
                get_family_plan_by_id,
            )

            plan = await get_family_plan_by_id(db, family.id)
            limit_value = plan.limits.get("max_family_members")
            if limit_value is None:
                limit_value = DEFAULT_FREE_LIMITS.get("max_family_members", 4)
            member_limit = int(limit_value)

            if member_limit != -1:  # -1 = unlimited
                member_count = (
                    await db.execute(
                        select(sa_func.count(User.id)).where(
                            User.family_id == family.id,
                            User.is_active == True,  # noqa: E712
                        )
                    )
                ).scalar_one()
                if member_count >= member_limit:
                    lang = "es" if (data.preferred_lang or "es") == "es" else "en"
                    detail = (
                        (
                            f"Esta familia alcanzó el límite de miembros de su plan "
                            f"({member_limit}). Pide a un padre/madre que mejore el "
                            f"plan para agregar más miembros."
                        )
                        if lang == "es"
                        else (
                            f"This family has reached its plan's member limit "
                            f"({member_limit}). Ask a parent to upgrade the plan "
                            f"to add more members."
                        )
                    )
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=detail,
                    )
        else:
            # No family_code — honor a pending email invitation for this address
            # before requiring a family_name / founding a new family. A parent
            # invited them by email; join THAT family instead of creating a
            # separate one (guards the invitation-bypass bug).
            pending_invite = await InvitationService.find_pending_for_email(
                db, data.email
            )
            if pending_invite is not None:
                family = (await db.execute(
                    select(Family).where(Family.id == pending_invite.family_id)
                )).scalar_one_or_none()
                if not family:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Invitation family not found.",
                    )
            else:
                # Create new family
                if not data.family_name:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Provide either a family_code or family_name.",
                    )

                # Founding an account requires explicit consent to the terms +
                # privacy notice (LFPDPPP). Reject when absent/false.
                if not data.accept_terms:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Debes aceptar los Términos y el Aviso de Privacidad "
                            "para crear tu cuenta."
                            if lang == "es"
                            else "You must accept the Terms and the Privacy Notice "
                            "to create your account."
                        ),
                    )

                # Validate the browser-supplied IANA timezone; fall back to UTC.
                fam_tz = "UTC"
                if data.timezone:
                    try:
                        from zoneinfo import ZoneInfo
                        ZoneInfo(data.timezone)
                        fam_tz = data.timezone
                    except Exception:
                        fam_tz = "UTC"
                family = Family(
                    name=data.family_name,
                    timezone=fam_tz,
                    join_code=generate_join_code(),
                )
                db.add(family)
                await db.flush()  # get family.id before creating user

        # Founders are PARENT. Join-by-code defaults to CHILD and is capped at
        # TEEN — PARENT can only be granted via email invitation or by founding
        # a family (a join code is shared with kids; it must not mint parents).
        if data.family_code:
            requested = UR(data.role) if data.role else UR.CHILD
            new_role = requested if requested in (UR.CHILD, UR.TEEN) else UR.CHILD
        elif pending_invite is not None:
            # Trust the role the parent set on the invitation (server-side).
            new_role = pending_invite.role
        else:
            new_role = UR.PARENT

        # Join-by-code signups start pending parental approval; every other
        # path is trusted (founder consented above, invitations are parent-sent).
        approval_status = APPROVAL_PENDING if data.family_code else APPROVAL_APPROVED
        now = datetime.now(timezone.utc)

        user = User(
            email=data.email,
            name=data.name,
            password_hash=get_password_hash(data.password),
            role=new_role,
            family_id=family.id,
            points=0,
            is_active=True,
            preferred_lang=data.preferred_lang,
            approval_status=approval_status,
            approved_at=now if approval_status == APPROVAL_APPROVED else None,
            birthdate=data.birthdate,
            # Record consent whenever the box was ticked (required for founders,
            # also sent by the join form).
            consented_at=now if data.accept_terms else None,
            consent_policy_version=CONSENT_POLICY_VERSION if data.accept_terms else None,
        )
        db.add(user)
        await db.flush()

        # If we created a new family, set created_by. NOT for the invite-join
        # path — that family already exists and has its own founder.
        if not data.family_code and pending_invite is None:
            family.created_by = user.id

        # Consume the invitation that steered this signup into an existing family.
        if pending_invite is not None:
            InvitationService.mark_accepted(pending_invite, user)

        await db.commit()
        await db.refresh(user)

        # Referral reward: a brand-new family that founded via ?ref=CODE is the
        # REFERRED party. Record the referral and grant BOTH families a 30-day
        # Plus credit (internal — no PayPal). Best-effort: never break signup.
        # Only for the new-family path (join-by-code accounts join an existing
        # family, they don't found one, so they can't be referred).
        if not data.family_code and pending_invite is None and data.ref:
            try:
                from app.services.referral_service import ReferralService

                referrer = await ReferralService.get_family_by_referral_code(
                    db, data.ref
                )
                if referrer is not None:
                    await ReferralService.record_referral_and_reward(
                        db,
                        referrer_family_id=referrer.id,
                        referred_family_id=family.id,
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "referral record/reward failed for new family %s (ref=%s)",
                    family.id, data.ref, exc_info=True,
                )
                # Ensure a failed referral never leaves a broken session for the
                # rest of registration (email send, token issue).
                try:
                    await db.rollback()
                except Exception:
                    pass

        # Onboarding hook: advance child_invited when joining an existing family
        if data.family_code:
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family.id, "child_invited", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance child_invited failed", exc_info=True
                )

        # Send verification email (non-blocking)
        try:
            await EmailService.send_verification_email(db, user, base_url=settings.email_link_base)
        except Exception:
            pass  # Don't block registration on email failure

        # Pending join-code signups get NO tokens — they must wait for a parent
        # to approve them from the members page. Notify the family's parents.
        if user.approval_status == APPROVAL_PENDING:
            try:
                await AuthService.notify_parents_of_pending_member(db, user)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "pending-member parent notification failed", exc_info=True
                )
            return RegisterFamilyResponse(
                access_token=None,
                refresh_token=None,
                token_type="bearer",
                user=UserResponse.model_validate(user),
                pending_approval=True,
                message=(
                    "Tu cuenta fue creada y está pendiente de aprobación. "
                    "Pide a tu papá o mamá que la apruebe desde la página de "
                    "Miembros para poder iniciar sesión."
                    if lang == "es"
                    else "Your account was created and is pending approval. "
                    "Ask a parent to approve it from the Members page before "
                    "you can log in."
                ),
            )

        # Issue access + refresh tokens
        access_token = create_access_token(
            data={"sub": str(user.id), "family_id": str(user.family_id), "role": user.role.value}
        )
        refresh_token = create_refresh_token(str(user.id), version=user.token_version)
        return RegisterFamilyResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user=UserResponse.model_validate(user),
        )

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

        # Soft-deleted (family closed): the account is gone even though its rows
        # survive the purge grace window. Same 401 as a deactivated account.
        if user.deleted_at is not None:
            raise UnauthorizedException("Account closed")

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
        user.updated_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def deactivate_user(db: AsyncSession, user_id: UUID) -> User:
        """Deactivate a user account.

        Open task assignments (pending/claimed/overdue) are cancelled in the
        same transaction — a deactivated member can never complete them, and
        leaving them alive rots the parent week grid with ghost rows that the
        sweep keeps flipping OVERDUE.
        """
        from sqlalchemy import update as sql_update
        from app.models.task_assignment import (
            AssignmentStatus,
            TaskAssignment,
        )

        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = False
        user.updated_at = datetime.now(timezone.utc)

        await db.execute(
            sql_update(TaskAssignment)
            .where(
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.status.in_([
                    AssignmentStatus.PENDING,
                    AssignmentStatus.CLAIMED,
                    AssignmentStatus.OVERDUE,
                ]),
            )
            .values(status=AssignmentStatus.CANCELLED)
        )

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def activate_user(db: AsyncSession, user_id: UUID) -> User:
        """Activate a user account"""
        user = await AuthService.get_user_by_id(db, user_id)
        user.is_active = True
        user.updated_at = datetime.now(timezone.utc)
        
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

        user.updated_at = datetime.now(timezone.utc)
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
        user.approved_at = datetime.now(timezone.utc)
        user.updated_at = datetime.now(timezone.utc)
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
