"""
Authentication routes

Handles user registration, login, token management,
email verification and password reset.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.core.security import hash_password
from app.core.type_utils import to_uuid_required
from app.services import AuthService
from app.services.email_service import EmailService
from app.schemas.user import (
    UserCreate,
    UserLogin,
    UserResponse,
    TokenResponse,
    UserPasswordUpdate,
    UserUpdate,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.models import User

router = APIRouter()


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    user_data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user and send a verification email."""
    user = await AuthService.register_user(db, user_data)
    # Send verification email (non-blocking — failure doesn't break registration)
    base_url = settings.BASE_URL
    await EmailService.send_verification_email(db, user, base_url=base_url)
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


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Consume an email verification token and mark the account as verified."""
    user = await EmailService.verify_email_token(db, body.token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token.",
        )
    return {"message": "Email verified successfully."}


@router.post("/resend-verification")
async def resend_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-send the verification email for the currently logged-in user."""
    if current_user.email_verified:
        return {"message": "Email is already verified."}
    await EmailService.send_verification_email(
        db, current_user, base_url=settings.BASE_URL
    )
    return {"message": "Verification email sent."}


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a password reset email. Always returns 200 to avoid user enumeration."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user and user.is_active:
        await EmailService.send_password_reset_email(
            db, user, base_url=settings.BASE_URL
        )
    # Always return the same response regardless of whether the email exists
    return {"message": "If an account with that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Consume a password reset token and set a new password."""
    token = await EmailService.verify_password_reset_token(db, body.token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )
    new_hash = hash_password(body.new_password)
    user = await EmailService.reset_password(db, token, new_hash)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not reset password.",
        )
    return {"message": "Password reset successfully. You can now log in."}

