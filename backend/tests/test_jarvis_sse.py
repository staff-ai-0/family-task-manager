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
