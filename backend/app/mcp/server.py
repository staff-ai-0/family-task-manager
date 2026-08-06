import json
from mcp.server import Server
from mcp.types import Tool, TextContent, ListToolsResult, CallToolResult
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


async def _on_list_tools(ctx, params) -> ListToolsResult:
    tools = []
    for spec in REGISTRY:
        for op in sorted(spec.ops):
            tools.append(Tool(
                name=tool_name(spec, op),
                description=dict(spec.op_descriptions).get(op, f"{op} {spec.domain}.{spec.name}"),
                input_schema=_input_schema(spec, op),
            ))
    return ListToolsResult(tools=tools)


async def _on_call_tool(ctx, params) -> CallToolResult:
    result = await dispatch_tool(params.name, params.arguments or {})
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(result, default=str))]
    )


def build_server() -> Server:
    register_builtin()
    # mcp 2.0 removed the typed decorators (@server.list_tools(), @server.call_tool())
    # from the low-level Server in favour of constructor-injected handlers that take
    # (ctx, params) and return a *Result model rather than a bare list. FastMCP is
    # gone from the package entirely, so this low-level form is the supported path.
    return Server(
        SERVER_NAME,
        on_list_tools=_on_list_tools,
        on_call_tool=_on_call_tool,
    )


server = build_server()
