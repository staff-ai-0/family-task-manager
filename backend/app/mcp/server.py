import json
from mcp.server import Server
from mcp.types import Tool, TextContent

SERVER_NAME = "family-pg"


def build_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name="ping",
                description="Health check; returns pong.",
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name == "ping":
            return [TextContent(type="text", text=json.dumps({"ok": True, "pong": True}))]
        return [TextContent(type="text", text=json.dumps({"ok": False, "error": f"unknown tool {name}"}))]

    return server


server = build_server()
