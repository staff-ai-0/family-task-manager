import pytest
from app.mcp.inproc import connected_mcp_session

from app.mcp.server import build_server


@pytest.mark.asyncio
async def test_server_lists_registry_tools():
    server = build_server()
    async with connected_mcp_session(server) as session:
        await session.initialize()
        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        assert "budget_account_list" in names
        assert "budget_account_create" in names
