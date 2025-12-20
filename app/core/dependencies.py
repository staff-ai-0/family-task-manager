from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.core.database import get_db
from app.core.security import decode_token, oauth2_scheme
from app.models.user import User, UserRole


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
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
    result = await db.execute(
        select(User).filter(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
    
    return user


def require_parent_role(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires parent role"""
    if current_user.role != UserRole.PARENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires parent privileges"
        )
    return current_user


def require_teen_or_parent(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that requires teen or parent role"""
    if current_user.role not in [UserRole.TEEN, UserRole.PARENT]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires teen or parent privileges"
        )
    return current_user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get current user from session cookie (optional, returns None if not authenticated)"""
    # Get user_id from session cookie
    user_id = request.cookies.get("user_id")
    
    if not user_id:
        return None
    
    try:
        # Get user from database
        result = await db.execute(
            select(User).filter(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        return user
    except Exception:
        return None


async def get_current_user_session(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user from session (raises exception if not authenticated)"""
    user = await get_optional_user(request, db)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    
    return user
