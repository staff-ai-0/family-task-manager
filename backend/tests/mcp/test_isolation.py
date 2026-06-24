# backend/tests/mcp/test_isolation.py
import json
import pytest
from app.mcp.server import build_server
from app.mcp.context import McpContext, use_context
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_account_from_family_a_invisible_to_family_b(db_session, family, other_family, parent_user, other_parent):
    server = build_server()
    # create under family A
    ctx_a = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    async with use_context(ctx_a):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            created = json.loads((await s.call_tool(
                "budget_account_create", {"name": "A-secret", "account_type": "checking"},
            )).content[0].text)
            acc_id = created["data"]["id"]
    # family B must NOT see it, and must NOT be able to get/update/delete it
    ctx_b = McpContext(family_id=other_family.id, user_id=other_parent.id, role="PARENT", db=db_session)
    async with use_context(ctx_b):
        async with create_connected_server_and_client_session(server) as s:
            await s.initialize()
            listed = json.loads((await s.call_tool("budget_account_list", {})).content[0].text)
            assert all(a["id"] != acc_id for a in listed["data"])
            got = json.loads((await s.call_tool("budget_account_get", {"id": acc_id})).content[0].text)
            assert got["ok"] is False  # NotFound, scoped out
            # client-supplied family_id must be ignored, not honored
            spoof = json.loads((await s.call_tool(
                "budget_account_get", {"id": acc_id, "family_id": str(family.id)},
            )).content[0].text)
            assert spoof["ok"] is False
