"""Jarvis SSE streaming test (W7.10).

Mocks the LLM to return a tool-call hop followed by a final reply, then
walks the async generator and asserts the event sequence + persistence.
"""

import json
import pytest
from unittest.mock import MagicMock

from app.services.jarvis_service import JarvisService


def _mk_message(content="", tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _mk_tool_call(call_id, name, arguments_json="{}"):
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments_json
    tc = MagicMock()
    tc.id = call_id
    tc.function = fn
    return tc


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch):
    from app.core import config
    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "test-key")
    monkeypatch.setattr(
        config.settings, "LITELLM_API_BASE", "https://litellm.test"
    )
    monkeypatch.setattr(config.settings, "JARVIS_DAILY_MESSAGE_CAP", 0)


async def _collect_events(gen):
    """Drain async generator, parse out [(event, data_dict), ...]."""
    events: list[tuple[str, dict]] = []
    async for line in gen:
        # Each yield is a full SSE block "event: X\ndata: {...}\n\n"
        ev = "message"
        data_str = ""
        for raw in line.splitlines():
            if raw.startswith("event: "):
                ev = raw[7:].strip()
            elif raw.startswith("data: "):
                data_str += raw[6:]
        try:
            data = json.loads(data_str) if data_str else {}
        except json.JSONDecodeError:
            data = {"raw": data_str}
        events.append((ev, data))
    return events


class TestSSEStream:
    async def test_no_tool_calls_thinking_reply_done(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        # Single hop: model returns content + no tool_calls.
        completion = _mk_message(content="Try tackling the dishes.")
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id, "what now?"
            )
        )
        names = [e for e, _ in events]
        assert names[0] == "thinking"
        assert "reply" in names
        assert names[-1] == "done"
        reply_payload = next(d for e, d in events if e == "reply")
        assert "dishes" in reply_payload["reply"].lower()
        assert reply_payload["actions"] == []
        assert "message_id" in reply_payload

    async def test_one_tool_hop_then_reply(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        # First call: tool_call. Second call: final reply.
        first = _mk_message(
            content="",
            tool_calls=[_mk_tool_call("c1", "tasks_today_list", "{}")],
        )
        second = _mk_message(content="Three tasks open today.")
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id, "status?"
            )
        )
        names = [e for e, _ in events]
        assert names.count("thinking") == 1
        assert names.count("tool") == 1
        assert names.count("reply") == 1
        assert names[-1] == "done"
        tool_payload = next(d for e, d in events if e == "tool")
        assert tool_payload["name"] == "tasks_today_list"
        assert tool_payload["ok"] is True

    async def test_error_on_missing_message(
        self, db_session, test_family, test_parent_user
    ):
        events = await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id, "   "
            )
        )
        names = [e for e, _ in events]
        assert "error" in names
        assert names[-1] == "done"

    async def test_persists_both_turns(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        completion = _mk_message(content="Hi parent.")
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id, "ping"
            )
        )

        history = await JarvisService.list_history(db_session, test_family.id)
        roles = [h.role for h in history]
        assert "user" in roles
        assert "assistant" in roles

    async def test_destructive_tool_emits_confirm_not_executed(
        self, db_session, test_family, test_parent_user, monkeypatch
    ):
        # Seed a template, then have the model "ask" to delete it. The
        # destructive op must be queued (confirm event), NOT executed inline.
        from app.schemas.task_template import TaskTemplateCreate
        from app.models.task_template import TaskTemplate
        from app.services.task_template_service import TaskTemplateService

        tmpl = await TaskTemplateService.create_template(
            db_session,
            TaskTemplateCreate(title="Doomed", points=0, is_bonus=False),
            test_family.id,
            test_parent_user.id,
        )

        first = _mk_message(
            content="",
            tool_calls=[
                _mk_tool_call(
                    "c1",
                    "tasks_template_delete",
                    json.dumps({"id": str(tmpl.id)}),
                )
            ],
        )
        second = _mk_message(content="Want me to delete it? Confirm first.")
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id, "delete Doomed"
            )
        )
        names = [e for e, _ in events]
        assert "confirm" in names
        assert "tool" not in names  # destructive op never executed inline
        confirm_payload = next(d for e, d in events if e == "confirm")
        assert confirm_payload["tool"] == "tasks_template_delete"
        assert "action_id" in confirm_payload

        # The template must still exist — nothing was deleted.
        still = await db_session.get(TaskTemplate, tmpl.id)
        assert still is not None


class TestTeenSelfCoach:
    """Teens get a tool-free, self-scoped coach on their own private thread."""

    async def test_teen_gets_no_tools_and_private_thread(
        self, db_session, test_family, test_teen_user, monkeypatch
    ):
        completion = _mk_message(content="Nice work — try one more task today!")
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            JarvisService._chat_stream_inner(
                db_session,
                test_family.id,
                test_teen_user.id,
                "how am I doing?",
                role="TEEN",
            )
        )
        names = [e for e, _ in events]
        assert "reply" in names and names[-1] == "done"

        # Tool-free: the completion call must NOT pass any tools/tool_choice —
        # structurally a teen cannot trigger a family-wide MCP tool.
        _, kwargs = client.chat.completions.create.call_args
        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs

        # Both persisted rows land on the teen's OWN thread (user_id == teen).
        from sqlalchemy import select
        from app.models.jarvis_message import JarvisMessage

        rows = (
            await db_session.execute(
                select(JarvisMessage).where(
                    JarvisMessage.family_id == test_family.id
                )
            )
        ).scalars().all()
        assert rows, "expected persisted messages"
        assert all(r.user_id == test_teen_user.id for r in rows)

    async def test_teen_thread_isolated_from_parent(
        self, db_session, test_family, test_parent_user, test_teen_user, monkeypatch
    ):
        client = MagicMock()
        client.chat.completions.create.return_value = _mk_message(content="ok")
        monkeypatch.setattr(
            "app.services.jarvis_service.OpenAI", lambda *a, **kw: client
        )

        # Parent turn (shared family-wide thread) then a teen turn (private).
        await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_parent_user.id,
                "parent secret", role="PARENT",
            )
        )
        await _collect_events(
            JarvisService._chat_stream_inner(
                db_session, test_family.id, test_teen_user.id,
                "teen question", role="TEEN",
            )
        )

        teen_hist = await JarvisService.list_history(
            db_session, test_family.id, user_id=test_teen_user.id, role="TEEN"
        )
        parent_hist = await JarvisService.list_history(
            db_session, test_family.id, user_id=test_parent_user.id, role="PARENT"
        )
        teen_texts = " ".join(m.content for m in teen_hist)
        parent_texts = " ".join(m.content for m in parent_hist)

        # Teen sees ONLY their own turn — never the parent's.
        assert "teen question" in teen_texts
        assert "parent secret" not in teen_texts
        # Parent's family-wide thread excludes the teen's private turn.
        assert "parent secret" in parent_texts
        assert "teen question" not in parent_texts
