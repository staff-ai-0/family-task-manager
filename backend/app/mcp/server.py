import json
from mcp.server import Server
from mcp.types import Tool, TextContent
from app.mcp.registry import REGISTRY, tool_name, register_builtin
from app.mcp.dispatch import dispatch_tool

SERVER_NAME = "family-pg"


def _input_schema(spec, op) -> dict:
    if op == "list":
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if op in ("get", "delete"):
        return {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    # Check for a custom op schema override (e.g. pet feed/interact).
    custom_schemas = dict(spec.custom_op_schemas)
    if op in custom_schemas:
        return custom_schemas[op].model_json_schema()
    # Standard CRUD schemas.
    if op == "create":
        schema = spec.create_schema.model_json_schema()
    else:
        # update or any other op falls back to update_schema
        schema = spec.update_schema.model_json_schema()
        if op == "update":
            schema.setdefault("properties", {})["id"] = {"type": "string"}
            schema["required"] = ["id"]
    return schema


def build_server() -> Server:
    register_builtin()
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        tools = []
        for spec in REGISTRY:
            for op in sorted(spec.ops):
                tools.append(Tool(
                    name=tool_name(spec, op),
                    description=dict(spec.op_descriptions).get(op, f"{op} {spec.domain}.{spec.name}"),
                    inputSchema=_input_schema(spec, op),
                ))
        return tools

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await dispatch_tool(name, arguments or {})
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


server = build_server()
