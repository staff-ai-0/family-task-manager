from uuid import UUID

from app.mcp.registry import REGISTRY, tool_name
from app.mcp.context import get_context


def _spec_for(name: str):
    for spec in REGISTRY:
        for op in spec.ops:
            if tool_name(spec, op) == name:
                return spec, op
    return None, None


async def dispatch_tool(name: str, arguments: dict) -> dict:
    spec, op = _spec_for(name)
    if spec is None:
        return {"ok": False, "error": f"unknown tool {name}"}
    # Never trust a client-supplied family_id: scope comes only from the context.
    arguments = {k: v for k, v in arguments.items() if k != "family_id"}
    ctx = get_context()
    try:
        if op == "list":
            return {"ok": True, "data": await spec.adapter.list(ctx)}
        if op == "get":
            return {"ok": True, "data": await spec.adapter.get(ctx, UUID(arguments["id"]))}
        if op == "create":
            payload = spec.create_schema(**arguments).model_dump(exclude_none=True)
            return {"ok": True, "data": await spec.adapter.create(ctx, payload)}
        if op == "update":
            eid = UUID(arguments.pop("id"))
            payload = spec.update_schema(**arguments).model_dump(exclude_none=True)
            return {"ok": True, "data": await spec.adapter.update(ctx, eid, payload)}
        if op == "delete":
            await spec.adapter.delete(ctx, UUID(arguments["id"]))
            return {"ok": True}
        return {"ok": False, "error": f"unsupported op {op}"}
    except Exception as e:  # surfaced to the LLM as a tool error, not a 500
        return {"ok": False, "error": str(e)}
