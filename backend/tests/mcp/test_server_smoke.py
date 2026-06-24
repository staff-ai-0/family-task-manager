import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp.server import build_server


@pytest.mark.asyncio
async def test_ping_tool_roundtrip():
    server = build_server()
    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert "ping" in [t.name for t in tools.tools]
        result = await session.call_tool("ping", {})
        payload = json.loads(result.content[0].text)
        assert payload == {"ok": True, "pong": True}
