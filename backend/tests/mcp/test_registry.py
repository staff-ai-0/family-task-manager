from app.mcp.registry import EntitySpec, ServiceAdapter, tool_name


def test_tool_name_convention():
    spec = EntitySpec(
        name="account", domain="budget", ops=frozenset({"list", "create"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset(),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
    )
    assert tool_name(spec, "create") == "budget_account_create"
    assert tool_name(spec, "list") == "budget_account_list"


def test_entity_spec_is_hashable():
    """EntitySpec must be hashable so it can safely be used in sets/dict keys.

    frozen=True + dict field would raise TypeError on hash(); the field is now
    stored as tuple[tuple[str,str],...] which is hashable.
    """
    spec = EntitySpec(
        name="offering", domain="gigs", ops=frozenset({"list", "delete"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset({"delete"}),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
        op_descriptions=(("delete", "soft-delete the offering"),),
    )
    # Must not raise TypeError
    h = hash(spec)
    assert isinstance(h, int)
    # Verify op_descriptions lookup still works (via dict() conversion in server.py)
    assert dict(spec.op_descriptions).get("delete") == "soft-delete the offering"
    assert dict(spec.op_descriptions).get("list") is None


def test_entity_spec_in_set():
    """EntitySpec instances can be stored in a set without TypeError."""
    spec_a = EntitySpec(
        name="a", domain="x", ops=frozenset({"list"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset(),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
    )
    spec_b = EntitySpec(
        name="b", domain="x", ops=frozenset({"list"}),
        create_schema=dict, update_schema=dict, destructive_ops=frozenset(),
        adapter=ServiceAdapter(), summarize=lambda op, p: "",
    )
    s = {spec_a, spec_b}
    assert len(s) == 2
