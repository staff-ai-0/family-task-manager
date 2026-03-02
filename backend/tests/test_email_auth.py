"""
Tests for email verification and password reset flows.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta, timezone

from app.models.email_verification import EmailVerificationToken
from app.models.password_reset import PasswordResetToken
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

class TestEmailVerification:
    """Test /api/auth/verify-email and /api/auth/resend-verification"""

    @pytest.mark.asyncio
    async def test_verify_email_valid_token(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Valid token marks user as verified."""
        # Create a real token in DB
        token = EmailVerificationToken(
            token=EmailVerificationToken.generate_token(),
            user_id=test_parent_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/verify-email",
            json={"token": token.token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "verified" in data["message"].lower()

        # User should now be marked as verified
        await db.refresh(test_parent_user)
        assert test_parent_user.email_verified is True

    @pytest.mark.asyncio
    async def test_verify_email_invalid_token(self, client: AsyncClient):
        """Invalid token returns 400."""
        response = await client.post(
            "/api/auth/verify-email",
            json={"token": "totally-invalid-token"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_email_expired_token(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Expired token returns 400."""
        token = EmailVerificationToken(
            token=EmailVerificationToken.generate_token(),
            user_id=test_parent_user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # already expired
        )
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/verify-email",
            json={"token": token.token},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_verify_email_already_used_token(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Used token returns 400."""
        token = EmailVerificationToken(
            token=EmailVerificationToken.generate_token(),
            user_id=test_parent_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_used=True,
        )
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/verify-email",
            json={"token": token.token},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_resend_verification_not_authenticated(self, client: AsyncClient):
        """Resend endpoint requires authentication."""
        response = await client.post("/api/auth/resend-verification")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_resend_verification_authenticated(
        self, client: AsyncClient, auth_headers
    ):
        """Authenticated user can request a new verification email."""
        with patch(
            "app.services.email_service.EmailService._send", return_value=True
        ):
            response = await client.post(
                "/api/auth/resend-verification",
                headers=auth_headers,
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class TestPasswordReset:
    """Test /api/auth/forgot-password and /api/auth/reset-password"""

    @pytest.mark.asyncio
    async def test_forgot_password_known_email(
        self, client: AsyncClient, test_parent_user
    ):
        """Forgot password always returns 200 (anti-enumeration)."""
        with patch(
            "app.services.email_service.EmailService._send", return_value=True
        ):
            response = await client.post(
                "/api/auth/forgot-password",
                json={"email": test_parent_user.email},
            )
        assert response.status_code == 200
        assert "sent" in response.json()["message"].lower() or "exists" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_forgot_password_unknown_email(self, client: AsyncClient):
        """Unknown email still returns 200 (no user enumeration)."""
        response = await client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_reset_password_valid_token(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Valid reset token allows password change."""
        token = PasswordResetToken.create_for_user(test_parent_user.id, hours_valid=1)
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/reset-password",
            json={"token": token.token, "new_password": "NewPassword123!"},
        )
        assert response.status_code == 200
        assert "reset" in response.json()["message"].lower()

        # Token should now be marked as used
        await db.refresh(token)
        assert token.is_used is True

    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """Invalid reset token returns 400."""
        response = await client.post(
            "/api/auth/reset-password",
            json={"token": "bad-token", "new_password": "NewPassword123!"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_password_expired_token(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Expired reset token returns 400."""
        token = PasswordResetToken(
            token=PasswordResetToken.generate_token(),
            user_id=test_parent_user.id,
            expires_at=datetime.utcnow() - timedelta(hours=2),
        )
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/reset-password",
            json={"token": token.token, "new_password": "NewPassword123!"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_reset_password_short_password(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """Password shorter than 8 chars is rejected by schema validation."""
        token = PasswordResetToken.create_for_user(test_parent_user.id, hours_valid=1)
        db.add(token)
        await db.commit()

        response = await client.post(
            "/api/auth/reset-password",
            json={"token": token.token, "new_password": "short"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_with_new_password_after_reset(
        self, client: AsyncClient, test_parent_user, db: AsyncSession
    ):
        """After reset, user can log in with the new password."""
        token = PasswordResetToken.create_for_user(test_parent_user.id, hours_valid=1)
        db.add(token)
        await db.commit()

        new_password = "BrandNew456!"

        await client.post(
            "/api/auth/reset-password",
            json={"token": token.token, "new_password": new_password},
        )

        # Login with new password
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": new_password},
        )
        assert login_resp.status_code == 200
        assert "access_token" in login_resp.json()
