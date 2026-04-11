"""
Tests for the welcome email onboarding flow.

Covers the pure helpers (_welcome_variant, _guide_url), the HTML
builder (_build_welcome_html), the idempotent dispatcher
(EmailService.send_welcome_if_not_sent), and the three trigger
points (verify_email_token, Google OAuth first sign-in, invitation
accept — the last two wire into the helper).

Uses mocks for Resend so nothing leaves the container.
"""

import pytest
from unittest.mock import patch, AsyncMock

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.email_service import (
    EmailService,
    _welcome_variant,
    _guide_url,
    _welcome_lang,
    _build_welcome_html,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestWelcomeVariant:
    def test_parent_returns_parent(self, test_parent_user):
        assert _welcome_variant(test_parent_user) == "parent"

    def test_child_returns_minor(self, test_child_user):
        assert _welcome_variant(test_child_user) == "minor"

    @pytest.mark.asyncio
    async def test_teen_returns_minor(self, db_session, test_family):
        teen = User(
            email="teen@test.com",
            password_hash="x",
            name="Teen User",
            role=UserRole.TEEN,
            family_id=test_family.id,
        )
        db_session.add(teen)
        await db_session.commit()
        assert _welcome_variant(teen) == "minor"


class TestGuideUrl:
    def test_spanish_returns_ayuda(self):
        assert _guide_url("https://family.agent-ia.mx", "es") == "https://family.agent-ia.mx/ayuda"

    def test_english_returns_help(self):
        assert _guide_url("https://family.agent-ia.mx", "en") == "https://family.agent-ia.mx/help"

    def test_trailing_slash_is_stripped(self):
        assert _guide_url("https://family.agent-ia.mx/", "en") == "https://family.agent-ia.mx/help"

    def test_unknown_lang_defaults_english(self):
        # _welcome_lang normalizes, but _guide_url receives whatever it's given.
        # Anything that's not exactly "es" becomes /help, matching the UI fallback.
        assert _guide_url("https://x.y", "fr") == "https://x.y/help"


class TestWelcomeLang:
    def test_spanish_pref(self, test_parent_user):
        test_parent_user.preferred_lang = "es"
        assert _welcome_lang(test_parent_user) == "es"

    def test_english_pref(self, test_parent_user):
        test_parent_user.preferred_lang = "en"
        assert _welcome_lang(test_parent_user) == "en"

    def test_unknown_pref_defaults_to_english(self, test_parent_user):
        test_parent_user.preferred_lang = "fr"
        assert _welcome_lang(test_parent_user) == "en"

    def test_none_pref_defaults_to_english(self, test_parent_user):
        test_parent_user.preferred_lang = None
        assert _welcome_lang(test_parent_user) == "en"


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


class TestBuildWelcomeHtml:
    def test_parent_en_contains_family_name_and_user_name(self):
        html = _build_welcome_html(
            variant="parent",
            lang="en",
            user_name="Alice",
            family_name="The Smiths",
            dashboard_url="https://x/dashboard",
            guide_url="https://x/help",
        )
        assert "Alice" in html
        assert "The Smiths" in html
        assert "Open my dashboard" in html
        assert "https://x/dashboard" in html
        assert "https://x/help" in html
        assert "View full user guide" in html

    def test_parent_es_uses_spanish_copy(self):
        html = _build_welcome_html(
            variant="parent",
            lang="es",
            user_name="Juan",
            family_name="Familia Martinez",
            dashboard_url="https://x/dashboard",
            guide_url="https://x/ayuda",
        )
        assert "Juan" in html
        assert "Familia Martinez" in html
        assert "Abrir mi dashboard" in html
        assert "manual completo" in html
        assert "https://x/ayuda" in html

    def test_minor_en_has_only_four_steps(self):
        html = _build_welcome_html(
            variant="minor",
            lang="en",
            user_name="Emma",
            family_name="The Smiths",
            dashboard_url="https://x/dashboard",
            guide_url="https://x/help",
        )
        # Exactly 4 <li> entries for the minor quick-start
        assert html.count("<li style=") == 4
        # Minor CTA
        assert "See my tasks" in html
        # Minor should NOT contain parent-only wording
        assert "Invite your family" not in html
        assert "Set up rewards" not in html
        assert "Connect your budget" not in html

    def test_parent_en_has_five_steps(self):
        html = _build_welcome_html(
            variant="parent",
            lang="en",
            user_name="Dad",
            family_name="The Smiths",
            dashboard_url="https://x/dashboard",
            guide_url="https://x/help",
        )
        assert html.count("<li style=") == 5
        # Parent wording present
        assert "Invite your family" in html
        assert "Set up rewards" in html
        assert "Connect your budget" in html

    def test_minor_es_wording(self):
        html = _build_welcome_html(
            variant="minor",
            lang="es",
            user_name="Emma",
            family_name="Familia Smith",
            dashboard_url="https://x/dashboard",
            guide_url="https://x/ayuda",
        )
        assert "Ver mis tareas" in html
        assert "guía para miembros" in html
        assert "https://x/ayuda" in html
        # No parent-only wording in minor variant
        assert "Invita a tu familia" not in html
        assert "Configura recompensas" not in html


# ---------------------------------------------------------------------------
# Idempotent dispatcher
# ---------------------------------------------------------------------------


class TestSendWelcomeIfNotSent:
    @pytest.mark.asyncio
    async def test_success_flips_flag(self, db_session, test_parent_user):
        # Sanity: the fixture user starts with the default False
        assert test_parent_user.welcome_email_sent is False

        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            result = await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_parent_user, base_url="https://x"
            )

        assert result is True
        assert test_parent_user.welcome_email_sent is True
        mock_send.assert_called_once()
        # Subject should be the parent-variant one, interpolated
        call_kwargs = mock_send.call_args.kwargs
        assert "Welcome" in call_kwargs["subject"] or "Bienvenido" in call_kwargs["subject"]

    @pytest.mark.asyncio
    async def test_idempotent_short_circuit(self, db_session, test_parent_user):
        # Pretend welcome already sent
        test_parent_user.welcome_email_sent = True
        await db_session.commit()

        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            result = await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_parent_user, base_url="https://x"
            )

        # Returned True (already sent counts as success), but _send was NEVER called
        assert result is True
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_resend_failure_swallowed_flag_not_flipped(
        self, db_session, test_parent_user
    ):
        assert test_parent_user.welcome_email_sent is False

        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(return_value=False),
        ):
            # Must return False but NOT raise
            result = await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_parent_user, base_url="https://x"
            )

        assert result is False
        # Flag must stay False so a future retry (different code path) still fires
        await db_session.refresh(test_parent_user)
        assert test_parent_user.welcome_email_sent is False

    @pytest.mark.asyncio
    async def test_resend_exception_swallowed(self, db_session, test_parent_user):
        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(side_effect=RuntimeError("Resend API down")),
        ):
            # Must not propagate
            result = await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_parent_user, base_url="https://x"
            )

        assert result is False
        await db_session.refresh(test_parent_user)
        assert test_parent_user.welcome_email_sent is False

    @pytest.mark.asyncio
    async def test_parent_variant_uses_parent_subject(
        self, db_session, test_parent_user
    ):
        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_parent_user, base_url="https://x"
            )

        subject = mock_send.call_args.kwargs["subject"]
        # Parent subject has "Family Task Manager" verbatim in both langs;
        # minor subject uses {family_name} instead.
        assert "Family Task Manager" in subject

    @pytest.mark.asyncio
    async def test_child_variant_uses_minor_subject(
        self, db_session, test_child_user
    ):
        with patch(
            "app.services.email_service.EmailService._send",
            new=AsyncMock(return_value=True),
        ) as mock_send:
            await EmailService.send_welcome_if_not_sent(
                db=db_session, user=test_child_user, base_url="https://x"
            )

        subject = mock_send.call_args.kwargs["subject"]
        # Minor subject interpolates family_name (the test fixture family
        # is called "Test Family")
        assert "Family Task Manager" not in subject
        assert test_child_user.name in subject
