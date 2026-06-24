"""Bridge MCP ``Tool`` objects to the OpenAI tool-calling schema.

Jarvis talks to the LiteLLM proxy with the OpenAI chat-completions tool
format. The MCP server is the source of truth for the tool list, so we map
each MCP ``Tool`` (name + description + JSON-Schema ``inputSchema``) onto the
``{"type": "function", "function": {...}}`` shape the LLM expects.
"""


def mcp_tools_to_openai(tools) -> list[dict]:
    """Map a list of MCP ``Tool`` objects to OpenAI function-tool dicts."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or t.name,
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]
