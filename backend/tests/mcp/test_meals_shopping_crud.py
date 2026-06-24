"""
Smoke tests for meals (recipe, planentry) + shopping (list, item) MCP tools
(Task 15, Phase 5).

Mirrors the structure of test_tasks_gigs_crud.py.
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
# meals — recipe LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_recipe_create_list_get_update_delete(db_session, family, parent_user):
    """Full LGCUD cycle for a recipe via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "meals_recipe_list" in tool_names
            assert "meals_recipe_get" in tool_names
            assert "meals_recipe_create" in tool_names
            assert "meals_recipe_update" in tool_names
            assert "meals_recipe_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "meals_recipe_create",
                {"name": "Tacos", "prep_minutes": 20},
            )).content[0].text)
            assert created["ok"] is True, created
            recipe_id = created["data"]["id"]
            assert created["data"]["name"] == "Tacos"

            # List
            listed = json.loads((await s.call_tool("meals_recipe_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(r["id"] == recipe_id for r in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "meals_recipe_get", {"id": recipe_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == recipe_id

            # Update
            updated = json.loads((await s.call_tool(
                "meals_recipe_update",
                {"id": recipe_id, "name": "Tacos al Pastor"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["name"] == "Tacos al Pastor"

            # Delete
            deleted = json.loads((await s.call_tool(
                "meals_recipe_delete", {"id": recipe_id},
            )).content[0].text)
            assert deleted["ok"] is True

            # Confirm gone
            gone = json.loads((await s.call_tool(
                "meals_recipe_get", {"id": recipe_id},
            )).content[0].text)
            assert gone["ok"] is False


# ---------------------------------------------------------------------------
# meals — planentry LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_planentry_create_list_get_update_delete(db_session, family, parent_user):
    """Full LGCUD cycle for a meal plan entry via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "meals_planentry_list" in tool_names
            assert "meals_planentry_get" in tool_names
            assert "meals_planentry_create" in tool_names
            assert "meals_planentry_update" in tool_names
            assert "meals_planentry_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "meals_planentry_create",
                {"plan_date": "2026-06-30", "meal_type": "dinner", "title": "Pasta Night"},
            )).content[0].text)
            assert created["ok"] is True, created
            entry_id = created["data"]["id"]
            assert created["data"]["title"] == "Pasta Night"

            # List (no date filter needed — returns all family plan entries)
            listed = json.loads((await s.call_tool("meals_planentry_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(e["id"] == entry_id for e in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "meals_planentry_get", {"id": entry_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == entry_id

            # Update
            updated = json.loads((await s.call_tool(
                "meals_planentry_update",
                {"id": entry_id, "title": "Pasta Night Deluxe"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["title"] == "Pasta Night Deluxe"

            # Delete
            deleted = json.loads((await s.call_tool(
                "meals_planentry_delete", {"id": entry_id},
            )).content[0].text)
            assert deleted["ok"] is True


# ---------------------------------------------------------------------------
# shopping — list LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_shopping_list_create_list_get_update_delete(db_session, family, parent_user):
    """Full LGCUD cycle for a shopping list via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "shopping_list_list" in tool_names
            assert "shopping_list_get" in tool_names
            assert "shopping_list_create" in tool_names
            assert "shopping_list_update" in tool_names
            assert "shopping_list_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "shopping_list_create",
                {"name": "Weekly Groceries"},
            )).content[0].text)
            assert created["ok"] is True, created
            list_id = created["data"]["id"]
            assert created["data"]["name"] == "Weekly Groceries"

            # List
            listed = json.loads((await s.call_tool("shopping_list_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(sl["id"] == list_id for sl in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "shopping_list_get", {"id": list_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == list_id

            # Update
            updated = json.loads((await s.call_tool(
                "shopping_list_update",
                {"id": list_id, "name": "Costco Run"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["name"] == "Costco Run"

            # Delete
            deleted = json.loads((await s.call_tool(
                "shopping_list_delete", {"id": list_id},
            )).content[0].text)
            assert deleted["ok"] is True


# ---------------------------------------------------------------------------
# shopping — item LGCUD
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_shopping_item_create_list_get_update_delete(db_session, family, parent_user):
    """Full LGCUD cycle for a shopping item via MCP tools."""
    from app.models.shopping import ShoppingList

    # Seed a shopping list so the item adapter can find one
    sl = ShoppingList(
        family_id=family.id,
        name="Seeded List",
        created_by=parent_user.id,
    )
    db_session.add(sl)
    await db_session.commit()
    await db_session.refresh(sl)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "shopping_item_list" in tool_names
            assert "shopping_item_get" in tool_names
            assert "shopping_item_create" in tool_names
            assert "shopping_item_update" in tool_names
            assert "shopping_item_delete" in tool_names

            # Create (adapter auto-picks the most recent active list)
            created = json.loads((await s.call_tool(
                "shopping_item_create",
                {"name": "Milk", "qty": "2L"},
            )).content[0].text)
            assert created["ok"] is True, created
            item_id = created["data"]["id"]
            assert created["data"]["name"] == "Milk"

            # List
            listed = json.loads((await s.call_tool("shopping_item_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(i["id"] == item_id for i in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "shopping_item_get", {"id": item_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == item_id

            # Update
            updated = json.loads((await s.call_tool(
                "shopping_item_update",
                {"id": item_id, "name": "Oat Milk", "qty": "1L"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["name"] == "Oat Milk"

            # Delete
            deleted = json.loads((await s.call_tool(
                "shopping_item_delete", {"id": item_id},
            )).content[0].text)
            assert deleted["ok"] is True
