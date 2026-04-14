"""
Tests for multi-audience Google OAuth verification.

Background: before this change the backend passed settings.GOOGLE_CLIENT_ID
as the audience to google.oauth2.id_token.verify_oauth2_token, which only
accepts a single aud. That broke iOS/Android clients which present tokens
issued under different Google Cloud client IDs (even though they share the
same project). Fix: call the library without an audience constraint and
validate aud ∈ settings.google_accepted_audiences ourselves.

These tests mock id_token.verify_oauth2_token so they don't need a real
Google token or network access.
"""

from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.core.exceptions import UnauthorizedException
from app.services.google_oauth_service import GoogleOAuthService


WEB_CLIENT = "355849593-42c0kgc5hbq2l0mr23g95b74jv3nprod.apps.googleusercontent.com"
IOS_CLIENT = "355849593-da0pomq1oejrsh80p4lcbu9hhu0rlms1.apps.googleusercontent.com"
UNKNOWN_CLIENT = "999999999999-evil-client.apps.googleusercontent.com"


def _valid_idinfo(aud: str) -> dict:
    return {
        "iss": "https://accounts.google.com",
        "aud": aud,
        "sub": "google-sub-12345",
        "email": "user@example.com",
        "name": "Test User",
        "picture": "https://example.com/pic.jpg",
        "email_verified": True,
    }


class TestGoogleAcceptedAudiences:
    """Settings.google_accepted_audiences union logic"""

    def test_empty_when_nothing_configured(self):
        s = Settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_IDS="")
        assert s.google_accepted_audiences == []

    def test_legacy_single_value_only(self):
        s = Settings(GOOGLE_CLIENT_ID=WEB_CLIENT, GOOGLE_CLIENT_IDS="")
        assert s.google_accepted_audiences == [WEB_CLIENT]

    def test_multi_value_comma_separated_string(self):
        s = Settings(
            GOOGLE_CLIENT_ID=WEB_CLIENT,
            GOOGLE_CLIENT_IDS=f"{IOS_CLIENT},some-other-client",
        )
        assert s.google_accepted_audiences == [WEB_CLIENT, IOS_CLIENT, "some-other-client"]

    def test_dedupes_overlap(self):
        s = Settings(
            GOOGLE_CLIENT_ID=WEB_CLIENT,
            GOOGLE_CLIENT_IDS=f"{WEB_CLIENT},{IOS_CLIENT}",
        )
        assert s.google_accepted_audiences == [WEB_CLIENT, IOS_CLIENT]

    def test_whitespace_is_trimmed(self):
        s = Settings(
            GOOGLE_CLIENT_ID="",
            GOOGLE_CLIENT_IDS=f"  {WEB_CLIENT}  ,  {IOS_CLIENT}  ",
        )
        assert s.google_accepted_audiences == [WEB_CLIENT, IOS_CLIENT]

    def test_only_multi_field(self):
        # GOOGLE_CLIENT_ID empty, all clients come from the new field
        s = Settings(GOOGLE_CLIENT_ID="", GOOGLE_CLIENT_IDS=f"{WEB_CLIENT},{IOS_CLIENT}")
        assert s.google_accepted_audiences == [WEB_CLIENT, IOS_CLIENT]


class TestVerifyGoogleToken:
    """GoogleOAuthService.verify_google_token multi-audience behavior"""

    @pytest.mark.asyncio
    async def test_web_client_token_accepted(self):
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = [WEB_CLIENT, IOS_CLIENT]
            mock_verify.return_value = _valid_idinfo(WEB_CLIENT)

            result = await GoogleOAuthService.verify_google_token("fake-web-token")

            assert result["email"] == "user@example.com"
            assert result["google_id"] == "google-sub-12345"
            # Library was called with audience=None — we validate aud ourselves
            _, call_kwargs = mock_verify.call_args
            assert call_kwargs.get("audience") is None

    @pytest.mark.asyncio
    async def test_ios_client_token_accepted(self):
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = [WEB_CLIENT, IOS_CLIENT]
            mock_verify.return_value = _valid_idinfo(IOS_CLIENT)

            result = await GoogleOAuthService.verify_google_token("fake-ios-token")

            assert result["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_unknown_client_rejected(self):
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = [WEB_CLIENT, IOS_CLIENT]
            mock_verify.return_value = _valid_idinfo(UNKNOWN_CLIENT)

            with pytest.raises(UnauthorizedException) as exc_info:
                await GoogleOAuthService.verify_google_token("fake-evil-token")

            assert "wrong audience" in str(exc_info.value).lower()
            assert UNKNOWN_CLIENT in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_allow_list_refuses_all_tokens(self):
        # Misconfiguration guard: if nobody populated client IDs, refuse
        # everything rather than silently trusting every Google token.
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = []

            with pytest.raises(UnauthorizedException) as exc_info:
                await GoogleOAuthService.verify_google_token("any-token")

            assert "no google client ids configured" in str(exc_info.value).lower()
            # Library must not even be called — fail-fast before signature check
            mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self):
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = [WEB_CLIENT]
            bad = _valid_idinfo(WEB_CLIENT)
            bad["iss"] = "https://evil.example.com"
            mock_verify.return_value = bad

            with pytest.raises(UnauthorizedException) as exc_info:
                await GoogleOAuthService.verify_google_token("token-from-bad-iss")

            assert "wrong issuer" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_library_value_error_propagates_as_unauthorized(self):
        # Expired / malformed tokens — library raises ValueError, we wrap
        with patch(
            "app.services.google_oauth_service.settings"
        ) as mock_settings, patch(
            "app.services.google_oauth_service.id_token.verify_oauth2_token"
        ) as mock_verify:
            mock_settings.google_accepted_audiences = [WEB_CLIENT]
            mock_verify.side_effect = ValueError("Token expired")

            with pytest.raises(UnauthorizedException) as exc_info:
                await GoogleOAuthService.verify_google_token("expired-token")

            assert "token expired" in str(exc_info.value).lower()
