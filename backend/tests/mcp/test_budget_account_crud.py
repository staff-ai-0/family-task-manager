import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_account_create_list_update_delete(db_session, family, user):
    server = build_server()
    ctx = McpContext(family_id=family.id, user_id=user.id, role="PARENT", db=db_session)
    async with use_context(ctx):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            assert "budget_account_create" in names

            created = json.loads((await s.call_tool(
                "budget_account_create",
                {"name": "Checking", "account_type": "checking", "starting_balance": 0},
            )).content[0].text)
            assert created["ok"] is True
            acc_id = created["data"]["id"]

            listed = json.loads((await s.call_tool("budget_account_list", {})).content[0].text)
            assert any(a["id"] == acc_id for a in listed["data"])

            updated = json.loads((await s.call_tool(
                "budget_account_update", {"id": acc_id, "name": "Checking 2"},
            )).content[0].text)
            assert updated["data"]["name"] == "Checking 2"

            deleted = json.loads((await s.call_tool("budget_account_delete", {"id": acc_id})).content[0].text)
            assert deleted["ok"] is True
