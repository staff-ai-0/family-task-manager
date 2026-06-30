"""Guards the Gemini-safe MCP→OpenAI tool-schema sanitizer.

Gemini strict-validates function schemas and rejects an array whose `items` is
missing or an empty `{}` — which Pydantic emits for a bare `list`/`Optional[list]`.
That 400'd every Jarvis call until `_gemini_safe` normalized the schemas.
"""
import pytest

from app.mcp.openai_bridge import _gemini_safe, mcp_tools_to_openai


def _arrays_have_typed_items(node) -> bool:
    """True if every array node has items with a usable type."""
    if isinstance(node, dict):
        if node.get("type") == "array":
            it = node.get("items")
            if not (isinstance(it, dict) and (
                it.get("type") or it.get("anyOf") or it.get("any_of")
                or it.get("properties") or it.get("$ref")
            )):
                return False
        return all(_arrays_have_typed_items(v) for v in node.values())
    if isinstance(node, list):
        return all(_arrays_have_typed_items(x) for x in node)
    return True


def test_empty_items_array_gets_typed():
    schema = {"type": "object", "properties": {
        "conditions": {"anyOf": [{"type": "array", "items": {}}, {"type": "null"}]}}}
    out = _gemini_safe(schema)
    assert _arrays_have_typed_items(out)
    assert out["properties"]["conditions"]["anyOf"][0]["items"]["type"] == "string"


def test_missing_items_array_gets_typed():
    out = _gemini_safe({"type": "array"})
    assert out["items"]["type"] == "string"


def test_typed_items_untouched():
    out = _gemini_safe({"type": "array", "items": {"type": "integer"}})
    assert out["items"]["type"] == "integer"


def test_object_items_untouched():
    out = _gemini_safe({"type": "array", "items": {"type": "object",
                                                    "properties": {"a": {"type": "string"}}}})
    assert out["items"]["type"] == "object"


@pytest.mark.asyncio
async def test_real_mcp_tools_all_gemini_safe():
    """Every tool the MCP server exposes must convert to a Gemini-safe schema."""
    from mcp.shared.memory import create_connected_server_and_client_session
    from app.mcp.server import server as mcp_server

    async with create_connected_server_and_client_session(mcp_server) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools

    converted = mcp_tools_to_openai(tools)
    assert converted, "expected a non-empty tool list"
    for t in converted:
        assert _arrays_have_typed_items(t["function"]["parameters"]), t["function"]["name"]
