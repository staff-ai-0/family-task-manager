"""
OAuth routes

Handles Google OAuth authentication.
"""

from fastapi import APIRouter, Depends, status, Body
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional

from app.core.database import get_db
from app.services.google_oauth_service import (
    GoogleOAuthService,
    OAuthApprovalPendingError,
    OAuthConsentRequiredError,
)
from app.schemas.user import UserResponse, TokenResponse


router = APIRouter()


class GoogleTokenRequest(BaseModel):
    """Request model for Google OAuth token"""
    token: str = Field(..., description="Google ID token from frontend")
    family_id: Optional[str] = Field(None, description="Family ID for new user registration")
    join_code: Optional[str] = Field(None, description="Family join code to join an existing family")
    role: Optional[str] = Field(
        None,
        pattern=r"^(parent|teen|child)$",
        description="Role when joining via join_code (defaults to child; "
        "capped at teen — parent is never granted via join code)",
    )
    accept_terms: Optional[bool] = Field(
        None,
        description="Terms + privacy-notice consent. REQUIRED (true) when "
        "the signup creates a NEW family; recorded when true.",
    )
    timezone: Optional[str] = Field(
        None,
        max_length=64,
        description="Browser IANA timezone; applied to the family when this "
        "sign-in creates a NEW one (invalid values fall back to UTC). Same "
        "capture as the password signup path.",
    )


@router.post("/google", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def google_oauth_login(
    request: GoogleTokenRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate with Google OAuth

    For existing users: Returns access token (join_code ignored). Accounts
    pending parental approval get 403 until a parent approves them.
    For new users with join_code/family_id: Joins the existing family as
    CHILD/TEEN (never PARENT) in PENDING state — 403 with a wait-for-parent
    message, NO tokens, and the family's parents are notified in-app.
    Joining is subject to the family plan's member cap: when the family is
    full this returns 403 with a plain-string bilingual ``detail`` (same
    shape as the join branch of POST /api/auth/register-family).
    For new users without join_code: Creates a new family (founder PARENT);
    requires accept_terms=true (consent is recorded).

    Structured error codes — a stable, machine-readable contract for the
    native iOS/Android clients registered via GOOGLE_CLIENT_IDS. Body is
    top-level ``{"error", "message", "message_es", "status_code"}``
    (``message`` is English, ``message_es`` Spanish — the same field shape
    as the ``email_not_verified`` contract):

    - 400 ``error="consent_required"``: the sign-in would CREATE a new
      family but ``accept_terms`` was not true. No account or family is
      created. Render a Terms + Privacy Notice consent screen and retry
      the same request with ``accept_terms=true``.
    - 403 ``error="approval_pending"``: join_code/family_id self-signup —
      the account exists (it IS created on the first attempt) but is
      pending parental approval; no tokens are issued until a parent
      approves from the Members page. Retrying returns the same 403.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Verify Google token
    google_user_info = await GoogleOAuthService.verify_google_token(request.token)
    logger.info(f"Google OAuth login attempt: email={google_user_info.get('email')}, join_code={request.join_code}")

    # Authenticate or create user
    try:
        user, access_token, refresh_token, is_new_user = await GoogleOAuthService.authenticate_or_create_user(
            db, google_user_info, request.family_id, request.join_code, request.role,
            accept_terms=bool(request.accept_terms),
            timezone=request.timezone,
        )
    except (OAuthConsentRequiredError, OAuthApprovalPendingError) as exc:
        # Structured, machine-readable contract (see docstring). Top-level
        # fields — not nested under "detail" — because every other error
        # this endpoint emits goes through the global exception handlers
        # (create_error_response), which use top-level error/message; the
        # web login page and native clients both read that shape.
        logger.info(
            f"Google OAuth blocked ({exc.code}): "
            f"email={google_user_info.get('email')}, join_code={request.join_code}"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message_en,
                "message_es": exc.message_es,
                "status_code": exc.status_code,
            },
        )

    logger.info(f"Google OAuth successful: user_id={user.id}, email={user.email}, family_id={user.family_id}, is_new={is_new_user}")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/google/verify", status_code=status.HTTP_200_OK)
async def verify_google_token(
    request: GoogleTokenRequest = Body(...),
):
    """
    Verify Google token and return user info without creating account
    
    Useful for checking if user exists before registration
    """
    google_user_info = await GoogleOAuthService.verify_google_token(request.token)
    
    return {
        "email": google_user_info["email"],
        "name": google_user_info["name"],
        "picture": google_user_info.get("picture"),
        "email_verified": google_user_info.get("email_verified", False),
    }
