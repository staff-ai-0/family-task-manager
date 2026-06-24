"""
Smoke tests for pet + consequences + notifications MCP tools (Task 17, Phase 5).

Mirrors test_budget_account_crud.py and test_tasks_gigs_crud.py.

Pet:  list / get + custom ops feed / interact (no create via MCP — pets are
      created via PetService.create_for_user, not via an MCP tool).
Consequences: LGCUD (delete is destructive).
Notifications: LGCD (already registered; smoke-tested here for completeness).
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
# pet — LG + feed / interact
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_pet_list_get_feed_interact(db_session, family, user):
    """
    Seed a KidPet directly; test list / get / feed / interact via MCP tools.

    create is NOT exposed as an MCP tool — pets are created via
    PetService.create_for_user (UI flow). The MCP layer only reads and
    interacts with an existing pet.
    """
    from app.models.kid_pet import KidPet

    pet = KidPet(
        user_id=user.id,
        name="Whiskers",
        species="cat",
        hunger=60,
        mood=50,
        xp=0,
    )
    db_session.add(pet)
    await db_session.commit()
    await db_session.refresh(pet)
    pet_id = str(pet.id)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            # Required tools
            assert "pet_pet_list" in tool_names
            assert "pet_pet_get" in tool_names
            assert "pet_pet_feed" in tool_names
            assert "pet_pet_interact" in tool_names
            # No create / update / delete via MCP
            assert "pet_pet_create" not in tool_names
            assert "pet_pet_delete" not in tool_names

            # List — should include our seeded pet
            listed = json.loads((await s.call_tool("pet_pet_list", {})).content[0].text)
            assert listed["ok"] is True, listed
            ids = [r["id"] for r in listed["data"]]
            assert pet_id in ids

            # Get
            got = json.loads((await s.call_tool(
                "pet_pet_get", {"id": pet_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == pet_id
            assert got["data"]["name"] == "Whiskers"

            # Feed — reduces hunger
            hunger_before = got["data"]["hunger"]
            fed = json.loads((await s.call_tool(
                "pet_pet_feed", {"user_id": str(user.id)},
            )).content[0].text)
            assert fed["ok"] is True, fed
            assert fed["data"]["hunger"] < hunger_before

            # Interact — boosts mood
            mood_before = fed["data"]["mood"]
            interacted = json.loads((await s.call_tool(
                "pet_pet_interact", {"user_id": str(user.id)},
            )).content[0].text)
            assert interacted["ok"] is True, interacted
            assert interacted["data"]["mood"] >= mood_before  # mood can't decrease from play


# ---------------------------------------------------------------------------
# consequences — LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_consequence_create_list_get_update_delete(db_session, family, parent_user, user):
    """Full CRUD cycle for consequences via MCP tools."""

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "consequences_consequence_list" in tool_names
            assert "consequences_consequence_get" in tool_names
            assert "consequences_consequence_create" in tool_names
            assert "consequences_consequence_update" in tool_names
            assert "consequences_consequence_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "consequences_consequence_create",
                {
                    "title": "No screen time",
                    "applied_to_user": str(user.id),
                    "restriction_type": "screen_time",
                    "severity": "low",
                    "duration_days": 2,
                },
            )).content[0].text)
            assert created["ok"] is True, created
            con_id = created["data"]["id"]
            assert created["data"]["title"] == "No screen time"

            # List
            listed = json.loads((await s.call_tool(
                "consequences_consequence_list", {},
            )).content[0].text)
            assert listed["ok"] is True
            assert any(c["id"] == con_id for c in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "consequences_consequence_get", {"id": con_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == con_id

            # Update
            updated = json.loads((await s.call_tool(
                "consequences_consequence_update",
                {"id": con_id, "title": "No screen time (extended)"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["title"] == "No screen time (extended)"

            # Delete
            deleted = json.loads((await s.call_tool(
                "consequences_consequence_delete", {"id": con_id},
            )).content[0].text)
            assert deleted["ok"] is True


# ---------------------------------------------------------------------------
# notifications — LGCD (already registered; smoke-test)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_notification_list_get_create_delete(db_session, family, parent_user):
    """LGCD smoke test for notifications via MCP tools."""

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "notifications_notification_list" in tool_names
            assert "notifications_notification_get" in tool_names
            assert "notifications_notification_create" in tool_names
            assert "notifications_notification_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "notifications_notification_create",
                {"title": "MCP smoke test", "body": "Hello"},
            )).content[0].text)
            assert created["ok"] is True, created
            notif_id = created["data"]["id"]

            # List
            listed = json.loads((await s.call_tool(
                "notifications_notification_list", {},
            )).content[0].text)
            assert listed["ok"] is True
            assert any(n["id"] == notif_id for n in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "notifications_notification_get", {"id": notif_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == notif_id

            # Delete
            deleted = json.loads((await s.call_tool(
                "notifications_notification_delete", {"id": notif_id},
            )).content[0].text)
            assert deleted["ok"] is True
