"""
Smoke tests for the points + rewards MCP tools (Task 13, Phase 5).

Mirrors the structure of test_budget_account_crud.py.
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
# points — ledger list/get + adjust create + transfer create
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_points_ledger_list_and_adjust(db_session, family, parent_user):
    """
    After a parent adjustment the ledger should show it.
    adjust is a destructive (money) op so the tool returns ok=True with data.
    """
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            # Required tools must be registered
            assert "points_ledger_list" in tool_names
            assert "points_ledger_get" in tool_names
            assert "points_adjust_create" in tool_names
            assert "points_transfer_create" in tool_names

            # Create a parent adjustment (money-moving op)
            result = json.loads((await s.call_tool(
                "points_adjust_create",
                {
                    "user_id": str(parent_user.id),
                    "points": 10,
                    "reason": "MCP smoke test",
                },
            )).content[0].text)
            assert result["ok"] is True, result
            txn_id = result["data"]["id"]
            assert result["data"]["points"] == 10

            # List ledger for the family — should contain the new transaction
            listed = json.loads((await s.call_tool("points_ledger_list", {})).content[0].text)
            assert listed["ok"] is True
            ids = [row["id"] for row in listed["data"]]
            assert txn_id in ids

            # Get the specific ledger entry
            got = json.loads((await s.call_tool(
                "points_ledger_get", {"id": txn_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == txn_id


@pytest.mark.anyio
async def test_points_transfer_create(db_session, family, parent_user, user):
    """
    Transfer from parent_user → user should create two ledger entries.
    We only check the successful return from the tool.
    """
    # Give parent enough points
    parent_user.points = 50
    db_session.add(parent_user)
    await db_session.commit()
    await db_session.refresh(parent_user)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            result = json.loads((await s.call_tool(
                "points_transfer_create",
                {
                    "from_user_id": str(parent_user.id),
                    "to_user_id": str(user.id),
                    "points": 5,
                    "reason": "transfer smoke test",
                },
            )).content[0].text)
            assert result["ok"] is True, result
            # Returns both transactions
            assert "debit" in result["data"]
            assert "credit" in result["data"]


# ---------------------------------------------------------------------------
# rewards — reward CRUD + redemption
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_reward_create_list_update_delete(db_session, family, parent_user):
    """Full CRUD cycle for a reward via MCP tools."""
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "rewards_reward_list" in tool_names
            assert "rewards_reward_get" in tool_names
            assert "rewards_reward_create" in tool_names
            assert "rewards_reward_update" in tool_names
            assert "rewards_reward_delete" in tool_names

            # Create
            created = json.loads((await s.call_tool(
                "rewards_reward_create",
                {
                    "title": "Extra Screen Time",
                    "points_cost": 50,
                    "category": "screen_time",
                },
            )).content[0].text)
            assert created["ok"] is True, created
            reward_id = created["data"]["id"]
            assert created["data"]["title"] == "Extra Screen Time"

            # List
            listed = json.loads((await s.call_tool("rewards_reward_list", {})).content[0].text)
            assert listed["ok"] is True
            assert any(r["id"] == reward_id for r in listed["data"])

            # Get
            got = json.loads((await s.call_tool(
                "rewards_reward_get", {"id": reward_id},
            )).content[0].text)
            assert got["ok"] is True
            assert got["data"]["id"] == reward_id

            # Update
            updated = json.loads((await s.call_tool(
                "rewards_reward_update",
                {"id": reward_id, "title": "Extra Screen Time v2"},
            )).content[0].text)
            assert updated["ok"] is True
            assert updated["data"]["title"] == "Extra Screen Time v2"

            # Delete
            deleted = json.loads((await s.call_tool(
                "rewards_reward_delete", {"id": reward_id},
            )).content[0].text)
            assert deleted["ok"] is True


@pytest.mark.anyio
async def test_redemption_list_and_create(db_session, family, parent_user, user):
    """
    Create a reward then redeem it as child user (user fixture is a PARENT but
    that's fine — the service only checks family membership + point balance).
    redemption_create is a money op.
    """
    # Give user enough points to redeem
    user.points = 100
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            tool_names = [t.name for t in (await s.list_tools()).tools]

            assert "rewards_redemption_list" in tool_names
            assert "rewards_redemption_create" in tool_names

            # Create a reward first
            created = json.loads((await s.call_tool(
                "rewards_reward_create",
                {"title": "Movie Night", "points_cost": 20, "category": "activities"},
            )).content[0].text)
            reward_id = created["data"]["id"]

            # Redeem (money-moving op)
            redeemed = json.loads((await s.call_tool(
                "rewards_redemption_create",
                {"reward_id": reward_id, "user_id": str(user.id)},
            )).content[0].text)
            assert redeemed["ok"] is True, redeemed
            assert "id" in redeemed["data"]

            # List redemptions for family — should include this one
            listed = json.loads((await s.call_tool("rewards_redemption_list", {})).content[0].text)
            assert listed["ok"] is True
