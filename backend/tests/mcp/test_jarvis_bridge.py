import pytest
from app.mcp.openai_bridge import mcp_tools_to_openai
from mcp.types import Tool


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_bridge_shapes_openai_function():
    tools = [Tool(name="budget_account_list", description="list", inputSchema={"type": "object", "properties": {}})]
    out = mcp_tools_to_openai(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "budget_account_list"
    assert out[0]["function"]["parameters"]["type"] == "object"


def test_bridge_falls_back_to_name_when_description_blank():
    # MCP Tool requires a dict inputSchema, but description may be empty.
    tools = [Tool(name="x_y_list", description="", inputSchema={"type": "object", "properties": {}})]
    out = mcp_tools_to_openai(tools)
    assert out[0]["function"]["description"] == "x_y_list"
    assert out[0]["function"]["parameters"]["type"] == "object"


@pytest.mark.anyio
async def test_mcp_tool_definitions_includes_migrated_tools():
    from app.services.jarvis_service import _mcp_tool_definitions

    defs = await _mcp_tool_definitions()
    names = {d["function"]["name"] for d in defs}
    # migrated legacy capabilities now live as registry tools
    for expected in (
        "tasks_template_create",
        "calendar_event_create",
        "shopping_item_create",
        "meals_recipe_create",
        "meals_planentry_create",
        "notifications_notification_create",
        "jarvis_schedule_create",
        "tasks_today_list",
        "tasks_pending_list",
        "tasks_overdue_list",
        "notifications_notification_list",
    ):
        assert expected in names, f"missing migrated tool {expected}"


@pytest.mark.anyio
async def test_execute_tool_roundtrips_through_mcp(db_session, family, parent_user):
    """_execute_tool dispatches through the in-memory MCP client, family-scoped."""
    from app.services.jarvis_service import JarvisService

    result = await JarvisService._execute_tool(
        db_session, family.id, parent_user.id,
        "tasks_template_create",
        {"title": "Vacuum", "is_bonus": True, "points": 25, "interval_days": 7},
    )
    assert result["ok"] is True
    assert result["data"]["title"] == "Vacuum"
    assert result["data"]["points"] == 25


@pytest.mark.anyio
async def test_execute_tool_mandatory_keeps_points(db_session, family, parent_user):
    """Two-currency economy: mandatory chores DO carry privilege points —
    the old clamp silently zeroed whatever Jarvis was asked to set."""
    from app.services.jarvis_service import JarvisService

    result = await JarvisService._execute_tool(
        db_session, family.id, parent_user.id,
        "tasks_template_create",
        {"title": "Make bed", "is_bonus": False, "points": 20},
    )
    assert result["ok"] is True
    assert result["data"]["points"] == 20
