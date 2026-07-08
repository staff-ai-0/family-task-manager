"""
Smoke tests for calendar (event) + chat (message) MCP tools
(Task 16, Phase 5).

calendar is already wired via _register_legacy_tools(); this test confirms
the tools are present and functional.  chat is the new domain added here.
"""

import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# calendar — event LGCUD (already registered via _register_legacy_tools)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_calendar_event_create_list_get_update_delete(db_session, family, parent_user):
    """Full LGCUD cycle for a calendar event via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "calendar_event_list" in tool_names
            assert "calendar_event_get" in tool_names
            assert "calendar_event_create" in tool_names
            assert "calendar_event_update" in tool_names
            assert "calendar_event_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "calendar_event_create",
                {"title": "Family Dinner", "start_iso": "2026-06-30T19:00:00"},
            )).content[0].text)
            assert created["ok"] is True, created
            event_id = created["data"]["id"]
            assert created["data"]["title"] == "Family Dinner"

            # List
            listed = json.loads((await s.call_tool("calendar_event_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(e["id"] == event_id for e in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "calendar_event_get", {"id": event_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == event_id

            # Update
            updated = json.loads((await s.call_tool(
                "calendar_event_update",
                {"id": event_id, "title": "Family Dinner 2.0"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["title"] == "Family Dinner 2.0"

            # Delete
            deleted = json.loads((await s.call_tool(
                "calendar_event_delete", {"id": event_id},
            )).content[0].text)
            assert deleted["ok"] is True

            # Confirm gone
            gone = json.loads((await s.call_tool(
                "calendar_event_get", {"id": event_id},
            )).content[0].text)
            assert gone["ok"] is False


# ---------------------------------------------------------------------------
# chat — message LGCD (no update; delete is destructive)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_chat_message_create_list_get_delete(db_session, family, parent_user):
    """LGCD cycle (no update) for a chat message via MCP tools."""
    # Reading chat via MCP requires the family's parental AI opt-in
    # (see test_ai_consent_gate.py for the gated behavior).
    family.ai_processing_consent = True
    await db_session.commit()

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "chat_message_list" in tool_names
            assert "chat_message_get" in tool_names
            assert "chat_message_create" in tool_names
            assert "chat_message_delete" in tool_names
            # no update tool
            assert "chat_message_update" not in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "chat_message_create",
                {"body": "Hello family!"},
            )).content[0].text)
            assert created["ok"] is True, created
            msg_id = created["data"]["id"]
            assert created["data"]["body"] == "Hello family!"

            # List
            listed = json.loads((await s.call_tool("chat_message_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(m["id"] == msg_id for m in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "chat_message_get", {"id": msg_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == msg_id
            assert got["data"]["body"] == "Hello family!"

            # Delete
            deleted = json.loads((await s.call_tool(
                "chat_message_delete", {"id": msg_id},
            )).content[0].text)
            assert deleted["ok"] is True

            # Confirm gone
            gone = json.loads((await s.call_tool(
                "chat_message_get", {"id": msg_id},
            )).content[0].text)
            assert gone["ok"] is False
