"""Bridge MCP ``Tool`` objects to the OpenAI tool-calling schema.

Jarvis talks to the LiteLLM proxy with the OpenAI chat-completions tool
format. The MCP server is the source of truth for the tool list, so we map
each MCP ``Tool`` (name + description + JSON-Schema ``inputSchema``) onto the
``{"type": "function", "function": {...}}`` shape the LLM expects.

Gemini (our only working upstream — see ``ALLOWED_MODELS`` in the jarvis
route) validates tool schemas far more strictly than OpenAI/Anthropic. In
particular it rejects an ``array`` whose ``items`` is missing or an empty
``{}`` (``GenerateContentRequest...items: missing field``). Pydantic emits
exactly that for a bare ``list`` / ``Optional[list]`` annotation, so a single
malformed tool used to 400 *every* Jarvis call. ``_gemini_safe`` normalizes
the JSON-Schema so no array reaches Gemini without a concrete ``items`` type —
defense in depth for all current and future tools, not just the one offender.
"""

import copy


def _gemini_safe(node):
    """Recursively normalize a JSON-Schema fragment so Gemini accepts it.

    The only transform: any ``array`` whose ``items`` is absent or has no
    usable type gets ``items = {"type": "string"}``. Everything else is left
    untouched. Mutates and returns ``node``.
    """
    if isinstance(node, dict):
        for key in ("anyOf", "oneOf", "allOf", "any_of", "one_of", "all_of"):
            if isinstance(node.get(key), list):
                node[key] = [_gemini_safe(s) for s in node[key]]
        if isinstance(node.get("properties"), dict):
            node["properties"] = {
                k: _gemini_safe(v) for k, v in node["properties"].items()
            }
        if "items" in node:
            node["items"] = _gemini_safe(node["items"])
        if node.get("type") == "array":
            items = node.get("items")
            has_type = isinstance(items, dict) and (
                items.get("type")
                or items.get("anyOf")
                or items.get("any_of")
                or items.get("properties")
                or items.get("$ref")
            )
            if not has_type:
                node["items"] = {"type": "string"}
        return node
    if isinstance(node, list):
        return [_gemini_safe(x) for x in node]
    return node


def mcp_tools_to_openai(tools) -> list[dict]:
    """Map a list of MCP ``Tool`` objects to OpenAI function-tool dicts."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or t.name,
                "parameters": _gemini_safe(
                    copy.deepcopy(t.inputSchema)
                    if t.inputSchema
                    else {"type": "object", "properties": {}}
                ),
            },
        }
        for t in tools
    ]
