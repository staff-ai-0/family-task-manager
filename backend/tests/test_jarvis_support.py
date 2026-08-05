"""Support mode (the support-ftm agent) — settings, LLM factory key override,
mode column, mode-scoped queries, the support chat/stream paths and routes.

Runtime counterpart of platform/agents/catalogue/support-ftm.md.
"""

import pytest
from unittest.mock import MagicMock

from app.core.config import Settings, settings
from app.core.llm import LLMNotConfiguredError, get_llm_client
from app.models.jarvis_message import JarvisMessage


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


from app.services.jarvis_service import JarvisService


async def _seed_msg(db, family_id, user_id, role, content, mode):
    row = JarvisMessage(
        family_id=family_id, user_id=user_id, role=role, content=content, mode=mode
    )
    db.add(row)
    await db.commit()
    return row


class TestModeScoping:
    async def test_history_is_mode_scoped(
        self, db_session, test_family, test_parent_user
    ):
        fid, uid = test_family.id, test_parent_user.id
        await _seed_msg(db_session, fid, uid, "user", "copilot q", "copilot")
        await _seed_msg(db_session, fid, None, "assistant", "copilot a", "copilot")
        await _seed_msg(db_session, fid, uid, "user", "support q", "support")
        await _seed_msg(db_session, fid, uid, "assistant", "support a", "support")

        copilot = await JarvisService.list_history(
            db_session, fid, user_id=uid, role="PARENT"
        )
        assert [m.content for m in copilot] == ["copilot q", "copilot a"]

        support = await JarvisService.list_history(
            db_session, fid, user_id=uid, role="PARENT", mode="support"
        )
        assert [m.content for m in support] == ["support q", "support a"]

    async def test_support_thread_is_per_user_even_for_parents(
        self, db_session, test_family, test_parent_user, test_teen_user
    ):
        fid = test_family.id
        await _seed_msg(
            db_session, fid, test_parent_user.id, "user", "parent support q", "support"
        )
        await _seed_msg(
            db_session, fid, test_teen_user.id, "user", "teen support q", "support"
        )

        parent_view = await JarvisService.list_history(
            db_session, fid, user_id=test_parent_user.id, role="PARENT", mode="support"
        )
        teen_view = await JarvisService.list_history(
            db_session, fid, user_id=test_teen_user.id, role="TEEN", mode="support"
        )
        assert [m.content for m in parent_view] == ["parent support q"]
        assert [m.content for m in teen_view] == ["teen support q"]

    async def test_today_message_count_is_mode_scoped(
        self, db_session, test_family, test_parent_user
    ):
        fid, uid = test_family.id, test_parent_user.id
        await _seed_msg(db_session, fid, uid, "user", "c1", "copilot")
        await _seed_msg(db_session, fid, uid, "user", "c2", "copilot")
        await _seed_msg(db_session, fid, uid, "user", "s1", "support")
        await _seed_msg(db_session, fid, uid, "user", "s2", "support")
        await _seed_msg(db_session, fid, uid, "user", "s3", "support")

        assert await JarvisService._today_message_count(db_session, fid) == 2
        assert (
            await JarvisService._today_message_count(db_session, fid, mode="support")
            == 3
        )

    async def test_clear_history_is_mode_and_user_scoped(
        self, db_session, test_family, test_parent_user, test_teen_user
    ):
        fid = test_family.id
        await _seed_msg(
            db_session, fid, test_parent_user.id, "user", "copilot q", "copilot"
        )
        await _seed_msg(
            db_session, fid, test_parent_user.id, "user", "parent support q", "support"
        )
        await _seed_msg(
            db_session, fid, test_teen_user.id, "user", "teen support q", "support"
        )

        # Parent clears THEIR support thread: teen's support + copilot survive.
        await JarvisService.clear_history(
            db_session, fid, user_id=test_parent_user.id, role="PARENT",
            mode="support",
        )
        from sqlalchemy import select
        remaining = [
            (m.content, m.mode)
            for m in (
                (await db_session.execute(
                    select(JarvisMessage).where(JarvisMessage.family_id == fid)
                )).scalars().all()
            )
        ]
        assert ("parent support q", "support") not in remaining
        assert ("teen support q", "support") in remaining
        assert ("copilot q", "copilot") in remaining

    async def test_support_history_excludes_other_parent_in_same_family(
        self, db_session, test_family, test_parent_user, test_parent_user_2
    ):
        # Discriminating regression for the "personal, even for parents"
        # requirement: with a SINGLE parent per family (the pre-existing
        # fixtures), the else-branch parent_ids predicate
        # (user_id IS NULL OR user_id IN parent_ids) would resolve to the
        # same one id as an explicit user_id filter — a removed
        # `if mode == "support":` branch would still pass. Two parents in
        # the SAME family exposes the gap: parent_ids now contains BOTH,
        # so only an explicit per-user filter keeps them apart.
        fid = test_family.id
        await _seed_msg(
            db_session, fid, test_parent_user.id, "user", "parent A support q",
            "support",
        )
        await _seed_msg(
            db_session, fid, test_parent_user_2.id, "user", "parent B support q",
            "support",
        )

        a_view = await JarvisService.list_history(
            db_session, fid, user_id=test_parent_user.id, role="PARENT",
            mode="support",
        )
        b_view = await JarvisService.list_history(
            db_session, fid, user_id=test_parent_user_2.id, role="PARENT",
            mode="support",
        )
        assert [m.content for m in a_view] == ["parent A support q"]
        assert [m.content for m in b_view] == ["parent B support q"]

    async def test_clear_support_history_does_not_touch_other_parent(
        self, db_session, test_family, test_parent_user, test_parent_user_2
    ):
        # Same discriminating gap as above, for the delete path: with only
        # one parent fixture, a removed `if mode == "support":` branch in
        # clear_history would still fall through to the parent_ids
        # else-branch and delete exactly that one parent's rows, passing
        # by accident. A second same-family parent proves the delete is
        # scoped to user_id, not "any parent".
        fid = test_family.id
        await _seed_msg(
            db_session, fid, test_parent_user.id, "user", "parent A support q",
            "support",
        )
        await _seed_msg(
            db_session, fid, test_parent_user_2.id, "user", "parent B support q",
            "support",
        )

        await JarvisService.clear_history(
            db_session, fid, user_id=test_parent_user.id, role="PARENT",
            mode="support",
        )
        from sqlalchemy import select
        remaining = [
            (m.content, m.mode)
            for m in (
                (await db_session.execute(
                    select(JarvisMessage).where(JarvisMessage.family_id == fid)
                )).scalars().all()
            )
        ]
        assert ("parent A support q", "support") not in remaining
        assert ("parent B support q", "support") in remaining


class TestSupportChat:
    @pytest.fixture(autouse=True)
    def _support_settings(self, monkeypatch):
        monkeypatch.setattr(settings, "LITELLM_API_KEY", "main-key")
        monkeypatch.setattr(settings, "SUPPORT_LITELLM_API_KEY", "support-key")
        monkeypatch.setattr(settings, "SUPPORT_MODEL", "claude-haiku")
        monkeypatch.setattr(settings, "SUPPORT_DAILY_MESSAGE_CAP", 30)
        monkeypatch.setattr(settings, "JARVIS_DAILY_MESSAGE_CAP", 100)
        monkeypatch.setattr(settings, "DEBUG", True)

    def _capture_llm(self, monkeypatch, reply="Ve a Ajustes y elige Miembros."):
        captured: dict = {}
        constructed: dict = {}
        client = MagicMock()

        def _create(**kwargs):
            captured.update(kwargs)
            return _mk_message(content=reply)

        client.chat.completions.create.side_effect = _create

        def _openai(**kwargs):
            constructed.update(kwargs)
            return client

        monkeypatch.setattr("app.core.llm.OpenAI", _openai)
        return captured, constructed, client

    async def test_support_persona_no_tools_pinned_model_support_key(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        from app.services.jarvis_service import SYSTEM_BASE, SYSTEM_SUPPORT

        captured, constructed, _ = self._capture_llm(monkeypatch)
        out = await JarvisService.chat(
            db_session,
            test_family.id,
            test_parent_user.id,
            "¿Cómo agrego un miembro a la familia?",
            model="gemini-2.5-flash",  # client override MUST be ignored
            preferred_lang="es",
            role="PARENT",
            mode="support",
        )
        assert out["reply"]
        assert out["actions"] == []
        # Pinned model, tool-free, dedicated key.
        assert captured["model"] == "claude-haiku"
        assert "tools" not in captured and "tool_choice" not in captured
        assert constructed["api_key"] == "support-key"
        # Support persona selected, copilot persona absent.
        sys_content = captured["messages"][0]["content"]
        assert SYSTEM_SUPPORT[:40] in sys_content
        assert SYSTEM_BASE[:40] not in sys_content

    async def test_grounding_is_guide_not_family_state(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        captured, _, _ = self._capture_llm(monkeypatch)
        await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "¿Cómo importo un CSV?", preferred_lang="es", role="PARENT",
            mode="support",
        )
        sys_content = captured["messages"][0]["content"]
        assert "TABLE OF CONTENTS" in sys_content
        assert "FAMILY STATE" not in sys_content

    async def test_guide_language_follows_preferred_lang(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        captured, _, _ = self._capture_llm(monkeypatch)
        await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "puntos", preferred_lang="es", role="PARENT", mode="support",
        )
        assert "Que es Family Task Manager" in captured["messages"][0]["content"]

        await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "points", preferred_lang="en", role="PARENT", mode="support",
        )
        assert "What is Family Task Manager" in captured["messages"][0]["content"]

    async def test_support_rows_persist_per_user_with_mode(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        self._capture_llm(monkeypatch)
        await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "hola soporte", preferred_lang="es", role="PARENT", mode="support",
        )
        from sqlalchemy import select
        rows = (
            await db_session.execute(
                select(JarvisMessage).where(
                    JarvisMessage.family_id == test_family.id
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(r.mode == "support" for r in rows)
        # Per-user thread even for a PARENT: both rows carry the user's id.
        assert all(r.user_id == test_parent_user.id for r in rows)

    async def test_caps_count_independently(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        from app.services.jarvis_service import JarvisQuotaExceeded

        self._capture_llm(monkeypatch)
        monkeypatch.setattr(settings, "SUPPORT_DAILY_MESSAGE_CAP", 1)
        # A copilot turn today must NOT count against the support cap.
        await _seed_msg(
            db_session, test_family.id, test_parent_user.id, "user", "c", "copilot"
        )
        out = await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "primera pregunta", preferred_lang="es", role="PARENT",
            mode="support",
        )
        assert out["reply"]
        # Now the support cap (1) is spent — next support turn is refused ...
        with pytest.raises(JarvisQuotaExceeded) as exc:
            await JarvisService.chat(
                db_session, test_family.id, test_parent_user.id,
                "segunda pregunta", preferred_lang="es", role="PARENT",
                mode="support",
            )
        assert "soporte@agent-ia.mx" in str(exc.value)
        # ... but the copilot cap (100) is untouched: copilot still works.
        out2 = await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "copilot sigue vivo?", preferred_lang="es", role="PARENT",
        )
        assert out2["reply"]

    async def test_upstream_failure_degrades_to_friendly_reply(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("proxy down")
        monkeypatch.setattr("app.core.llm.OpenAI", lambda *a, **kw: client)

        out = await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "ayuda", preferred_lang="es", role="PARENT", mode="support",
        )
        # Never a raw upstream error: bilingual friendly copy + human channel.
        assert "soporte@agent-ia.mx" in out["reply"]

    async def test_prod_without_support_key_fails_closed(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        from app.services.jarvis_service import JarvisSupportNotConfigured

        monkeypatch.setattr(settings, "SUPPORT_LITELLM_API_KEY", "")
        monkeypatch.setattr(settings, "DEBUG", False)
        with pytest.raises(JarvisSupportNotConfigured):
            await JarvisService.chat(
                db_session, test_family.id, test_parent_user.id,
                "hola", preferred_lang="es", role="PARENT", mode="support",
            )

    async def test_dev_falls_back_to_main_key(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        monkeypatch.setattr(settings, "SUPPORT_LITELLM_API_KEY", "")
        monkeypatch.setattr(settings, "DEBUG", True)
        _, constructed, _ = self._capture_llm(monkeypatch)
        await JarvisService.chat(
            db_session, test_family.id, test_parent_user.id,
            "hola", preferred_lang="es", role="PARENT", mode="support",
        )
        assert constructed["api_key"] == "main-key"
