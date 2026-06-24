from app.mcp.registry import EntitySpec, ServiceAdapter, tool_name


def test_tool_name_convention():
    spec = EntitySpec(
        name="account", domain="budget", ops=frozenset({"list", "create"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset(),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
    )
    assert tool_name(spec, "create") == "budget_account_create"
    assert tool_name(spec, "list") == "budget_account_list"
