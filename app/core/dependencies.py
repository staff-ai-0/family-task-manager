from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from uuid import UUID

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
    payload = decode_token(token)
    user_id: str = payload.get("sub")

    if user_id is None:
        raise credentials_exception

    # Get user from database
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user


def require_parent_role(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires parent role"""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires parent privileges",
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
