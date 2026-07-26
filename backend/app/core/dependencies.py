from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token, oauth2_scheme
from app.core.type_utils import to_uuid_required
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.user import User, UserRole


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Decode token
    payload = decode_token(token, expected_type="access")
    user_id: str = payload.get("sub")

    if user_id is None:
        raise credentials_exception

    # Get user from database
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    # A still-valid access token must stop working once the account is
    # deactivated. Login already gates is_active; mirror it on every request.
    if not user.is_active:
        raise credentials_exception

    # Soft-deleted (family closed): treat the account as gone on every request,
    # even while its rows survive the 30-day purge grace window. Setting
    # families.deleted_at also stamps every member's users.deleted_at, so this
    # single-column check on the already-loaded user covers a closed family too
    # (no extra family query on the hot path).
    if user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account closed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await _touch_last_seen(db, user)

    return user


async def _touch_last_seen(db: AsyncSession, user: User) -> None:
    """Throttled, best-effort activity stamp.

    The write runs inside a SAVEPOINT (``begin_nested``) rather than a
    plain session-level statement: a SAVEPOINT rollback only expires
    ORM-dirty objects, and this function never mutates `user` before a
    successful write, so `user` is never expired by a failure here — no
    recovery read is needed. A bare ``db.rollback()`` would instead expire
    every object in the identity map unconditionally, forcing an illegal
    synchronous lazy-load on `user` in the caller. Any failure — from the
    write or from the final commit — is swallowed: an instrumentation
    write must never break the request it is measuring. The naive
    (tzinfo-less) guard covers a value that reached the column outside
    SQLAlchemy (e.g. a raw-SQL backfill).
    """
    now = datetime.now(timezone.utc)
    try:
        last_seen = user.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = None
        throttle = timedelta(minutes=settings.LAST_SEEN_THROTTLE_MINUTES)
        if last_seen is not None and now - last_seen < throttle:
            return
        async with db.begin_nested():
            await db.execute(
                update(User).where(User.id == user.id).values(last_seen_at=now)
            )
        await db.commit()
        user.last_seen_at = now
    except Exception:
        pass


def require_parent_role(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires parent role"""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires parent privileges",
        )
    return current_user


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Platform operator. Requires BOTH the DB flag and the env allowlist.

    Rejects with 404 rather than 403 so the admin surface is not
    discoverable — a 403 confirms the route exists. Both conditions are
    required on purpose: the DB flag alone would let a stolen dump mint an
    operator, and the allowlist alone would hand platform powers to anyone
    who gains control of a listed mailbox.
    """
    if not current_user.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
    if (current_user.email or "").lower() not in settings.superadmin_emails_set:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
        )
    return current_user


def require_teen_or_parent(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires teen or parent role"""
    if current_user.role not in [UserRole.TEEN, UserRole.PARENT]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires teen or parent privileges",
        )
    return current_user


def ensure_email_verified(user: User) -> None:
    """Guard actions that trigger email to third-party addresses.

    Unverified accounts must not be able to spray outbound mail (family
    invitations, etc.) — that is the classic spam-signup vector and burns
    sender reputation. Call inside a route AFTER role checks. Raises 403
    with a structured, bilingual detail so the frontend can message it
    (``error`` is the machine code; ``message``/``message_es`` the copy).
    """
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "email_not_verified",
                "message": (
                    "Please verify your email address before inviting others. "
                    "Check your inbox for the verification link or request a new one."
                ),
                "message_es": (
                    "Verifica tu correo electrónico antes de invitar a otras personas. "
                    "Revisa tu bandeja de entrada o solicita un nuevo enlace de verificación."
                ),
            },
        )


async def get_optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user from session cookie (optional, returns None if not authenticated)"""
    # Get user_id from session cookie
    user_id = request.cookies.get("user_id")

    if not user_id:
        return None

    try:
        # Get user from database
        result = await db.execute(select(User).filter(User.id == user_id))
        user = result.scalar_one_or_none()
        # A soft-deleted (closed) account must not resolve from an SSR session
        # cookie either — treat it as anonymous.
        if user is not None and user.deleted_at is not None:
            return None
        return user
    except Exception:
        return None


async def get_current_user_session(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user from session (raises exception if not authenticated)"""
    user = await get_optional_user(request, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    return user


# Family Authorization Dependencies


async def verify_family_access(
    resource_family_id: UUID, current_user: User = Depends(get_current_user)
) -> None:
    """
    Verify user has access to family-scoped resource.

    Args:
        resource_family_id: Family ID of the resource being accessed
        current_user: Currently authenticated user

    Raises:
        ForbiddenException: If user doesn't belong to resource's family
    """
    user_family_id = to_uuid_required(current_user.family_id)
    if resource_family_id != user_family_id:
        raise ForbiddenException("Access denied: resource belongs to different family")


async def get_family_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Get user and verify family membership.

    Args:
        user_id: User ID to fetch
        current_user: Currently authenticated user
        db: Database session

    Returns:
        User object if found and in same family

    Raises:
        NotFoundException: If user not found
        ForbiddenException: If user not in same family
    """
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise NotFoundException(f"User with ID {user_id} not found")

    user_family_id = to_uuid_required(user.family_id)
    current_family_id = to_uuid_required(current_user.family_id)

    if user_family_id != current_family_id:
        raise ForbiddenException("Access denied: user not in same family")

    return user


async def verify_family_id(
    family_id: UUID, current_user: User = Depends(get_current_user)
) -> UUID:
    """
    Verify family ID matches current user's family.

    Args:
        family_id: Family ID to verify
        current_user: Currently authenticated user

    Returns:
        The family_id if it matches

    Raises:
        ForbiddenException: If family_id doesn't match
    """
    current_family_id = to_uuid_required(current_user.family_id)
    if family_id != current_family_id:
        raise ForbiddenException(
            "Access denied: cannot access other family's resources"
        )
    return family_id
