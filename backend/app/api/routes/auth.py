"""
Authentication routes

Handles user registration, login, token management.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.type_utils import to_uuid_required
from app.services import AuthService
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    UserPasswordUpdate,
    UserUpdate,
)
from app.models import User

router = APIRouter()


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user"""
    user = await AuthService.register_user(db, user_data)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    login_data: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """Login and get access token"""
    user, access_token = await AuthService.authenticate_user(db, login_data)
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Logout (invalidate token)"""
    return {
        "message": "Logged out successfully. Please delete the token on client side."
    }


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current user information"""
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user profile (name, preferred_lang)"""
    # Only allow self-update of safe fields (not role, is_active)
    safe_fields = {
        k: v
        for k, v in update_data.model_dump(exclude_unset=True).items()
        if k in ("name", "preferred_lang")
    }
    if not safe_fields:
        return current_user

    user = await AuthService.update_profile(
        db, to_uuid_required(current_user.id), safe_fields
    )
    return user


@router.put("/password", response_model=UserResponse)
async def update_password(
    password_data: UserPasswordUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update user password"""
    user = await AuthService.update_password(
        db,
        to_uuid_required(current_user.id),
        password_data.current_password,
        password_data.new_password,
    )
    return user
