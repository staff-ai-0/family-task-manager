"""Frankie SSE streaming test (W7.10).

Mocks the LLM to return a tool-call hop followed by a final reply, then
walks the async generator and asserts the event sequence + persistence.
"""

import json
import pytest
from unittest.mock import MagicMock

from app.services.frankie_service import FrankieService


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
    monkeypatch.setattr(config.settings, "FRANKIE_DAILY_MESSAGE_CAP", 0)


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
            "app.services.frankie_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            FrankieService.chat_stream(
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
            tool_calls=[_mk_tool_call("c1", "list_today_progress", "{}")],
        )
        second = _mk_message(content="Three tasks open today.")
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]
        monkeypatch.setattr(
            "app.services.frankie_service.OpenAI", lambda *a, **kw: client
        )

        events = await _collect_events(
            FrankieService.chat_stream(
                db_session, test_family.id, test_parent_user.id, "status?"
            )
        )
        names = [e for e, _ in events]
        assert names.count("thinking") == 1
        assert names.count("tool") == 1
        assert names.count("reply") == 1
        assert names[-1] == "done"
        tool_payload = next(d for e, d in events if e == "tool")
        assert tool_payload["name"] == "list_today_progress"
        assert tool_payload["ok"] is True

    async def test_error_on_missing_message(
        self, db_session, test_family, test_parent_user
    ):
        events = await _collect_events(
            FrankieService.chat_stream(
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
            "app.services.frankie_service.OpenAI", lambda *a, **kw: client
        )

        await _collect_events(
            FrankieService.chat_stream(
                db_session, test_family.id, test_parent_user.id, "ping"
            )
        )

        history = await FrankieService.list_history(db_session, test_family.id)
        roles = [h.role for h in history]
        assert "user" in roles
        assert "assistant" in roles
