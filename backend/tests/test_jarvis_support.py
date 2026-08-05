"""Support mode (the support-ftm agent) — settings, LLM factory key override,
mode column, mode-scoped queries, the support chat/stream paths and routes.

Runtime counterpart of platform/agents/catalogue/support-ftm.md.
"""

import pytest
from unittest.mock import MagicMock

from app.core.config import Settings, settings
from app.core.llm import LLMNotConfiguredError, get_llm_client


# ---------------------------------------------------------------------------
# Shared LLM-mock helpers (same shape as tests/test_jarvis_sse.py).
# ---------------------------------------------------------------------------

def _mk_message(content="", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


class TestSupportSettings:
    def test_field_defaults(self):
        # Assert on the field DEFAULTS, not the live singleton — a dev .env
        # with SUPPORT_* overrides must not flip this test.
        assert Settings.model_fields["SUPPORT_MODEL"].default == "claude-haiku"
        assert Settings.model_fields["SUPPORT_LITELLM_API_KEY"].default == ""
        assert Settings.model_fields["SUPPORT_DAILY_MESSAGE_CAP"].default == 30


class TestLlmClientApiKeyOverride:
    def test_override_key_wins(self, monkeypatch):
        monkeypatch.setattr(settings, "LITELLM_API_KEY", "main-key")
        assert get_llm_client(api_key="support-key").api_key == "support-key"

    def test_default_key_unchanged(self, monkeypatch):
        monkeypatch.setattr(settings, "LITELLM_API_KEY", "main-key")
        assert get_llm_client().api_key == "main-key"

    def test_override_works_without_main_key(self, monkeypatch):
        monkeypatch.setattr(settings, "LITELLM_API_KEY", "")
        assert get_llm_client(api_key="support-key").api_key == "support-key"

    def test_no_key_at_all_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "LITELLM_API_KEY", "")
        with pytest.raises(LLMNotConfiguredError):
            get_llm_client()


class TestModeColumn:
    async def test_mode_defaults_to_copilot(
        self, db_session, test_family, test_parent_user
    ):
        from app.models.jarvis_message import JarvisMessage

        row = JarvisMessage(
            family_id=test_family.id,
            user_id=test_parent_user.id,
            role="user",
            content="hi",
        )
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)
        assert row.mode == "copilot"

    async def test_mode_accepts_support(
        self, db_session, test_family, test_parent_user
    ):
        from app.models.jarvis_message import JarvisMessage

        row = JarvisMessage(
            family_id=test_family.id,
            user_id=test_parent_user.id,
            role="user",
            content="hi",
            mode="support",
        )
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)
        assert row.mode == "support"
