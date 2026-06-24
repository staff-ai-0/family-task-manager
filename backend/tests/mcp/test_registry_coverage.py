"""Task 20: Registry coverage test.

Parametrizes over the full REGISTRY and asserts structural invariants:

1. Every op declared in spec.ops has a concrete adapter method (not the base
   NotImplementedError from ServiceAdapter):
   - Standard ops (list/get/create/update/delete): adapter method overridden.
   - Custom ops (e.g. feed/interact): adapter has call_custom() overridden.

2. create_schema and update_schema are pydantic BaseModel subclasses when
   the corresponding op is present in ops; they may be dict when the op is
   absent (no schema validation needed).

3. destructive_ops is a subset of ops (no phantom destructive op).

4. No two specs produce the same tool name (no collisions across the whole
   registry).

Run: podman exec -e PYTHONPATH=/app family_app_backend pytest tests/mcp/test_registry_coverage.py --no-cov -v
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel

# Importing the registry triggers register_builtin() indirectly via server
# import.  We call register_builtin() explicitly to ensure the REGISTRY is
# populated even when the module is imported standalone.
from app.mcp.registry import REGISTRY, tool_name, register_builtin
from app.mcp.adapters import ServiceAdapter

# Standard ops that map to named methods on ServiceAdapter.
_STANDARD_OPS = frozenset({"list", "get", "create", "update", "delete"})

# Custom ops are anything NOT in _STANDARD_OPS; they must be handled by
# adapter.call_custom().  We verify call_custom is overridden.
_CUSTOM_OPS_SENTINEL = "call_custom"


def _method_is_overridden(adapter: ServiceAdapter, method_name: str) -> bool:
    """Return True when *adapter* overrides *method_name* relative to the base.

    We compare the method's defining class against ServiceAdapter so that a
    subclass that defines the method itself returns True.
    """
    method = getattr(type(adapter), method_name, None)
    base_method = getattr(ServiceAdapter, method_name, None)
    # The method is overridden if it exists on the subclass and is NOT the
    # exact same function object as the one on ServiceAdapter.
    return method is not None and method is not base_method


@pytest.fixture(scope="module", autouse=True)
def ensure_registry_populated():
    """Populate REGISTRY before any test in this module runs."""
    if not REGISTRY:
        register_builtin()


# ── parametrize ───────────────────────────────────────────────────────────────
# We use a module-level fixture to build the param list AFTER ensuring the
# registry is populated.  Since fixtures run before parametrize evaluation in
# pytest, we fall back to calling register_builtin() at collection time here.
def _specs():
    if not REGISTRY:
        register_builtin()
    return REGISTRY


# ── test: adapter implements every declared op ────────────────────────────────

@pytest.mark.parametrize("spec", _specs(), ids=lambda s: f"{s.domain}.{s.name}")
def test_adapter_implements_all_ops(spec):
    """Every op in spec.ops must be backed by a concrete adapter method.

    Standard ops (list/get/create/update/delete) must be overridden individually.
    Custom ops (anything else, e.g. feed/interact) must have call_custom overridden.
    """
    adapter = spec.adapter
    custom_ops = spec.ops - _STANDARD_OPS

    for op in spec.ops & _STANDARD_OPS:
        assert _method_is_overridden(adapter, op), (
            f"{spec.domain}.{spec.name}: adapter {type(adapter).__name__} "
            f"does not override '{op}' (still raises NotImplementedError from base)"
        )

    if custom_ops:
        assert _method_is_overridden(adapter, _CUSTOM_OPS_SENTINEL), (
            f"{spec.domain}.{spec.name}: adapter {type(adapter).__name__} "
            f"declares custom ops {custom_ops!r} but does not override call_custom()"
        )


# ── test: schemas are BaseModel when the op is present ───────────────────────

@pytest.mark.parametrize("spec", _specs(), ids=lambda s: f"{s.domain}.{s.name}")
def test_schemas_are_basemodel_when_op_present(spec):
    """create_schema/update_schema must be BaseModel subclasses when the op exists."""
    if "create" in spec.ops:
        assert (
            isinstance(spec.create_schema, type) and issubclass(spec.create_schema, BaseModel)
        ), (
            f"{spec.domain}.{spec.name}: 'create' in ops but create_schema "
            f"is {spec.create_schema!r}, not a BaseModel subclass"
        )
    if "update" in spec.ops:
        assert (
            isinstance(spec.update_schema, type) and issubclass(spec.update_schema, BaseModel)
        ), (
            f"{spec.domain}.{spec.name}: 'update' in ops but update_schema "
            f"is {spec.update_schema!r}, not a BaseModel subclass"
        )


# ── test: destructive_ops ⊆ ops ───────────────────────────────────────────────

@pytest.mark.parametrize("spec", _specs(), ids=lambda s: f"{s.domain}.{s.name}")
def test_destructive_ops_subset_of_ops(spec):
    """destructive_ops must be a subset of ops (no phantom destructive entries)."""
    phantom = spec.destructive_ops - spec.ops
    assert not phantom, (
        f"{spec.domain}.{spec.name}: destructive_ops contains ops "
        f"not in ops: {phantom!r}"
    )


# ── test: no tool-name collisions across the whole registry ──────────────────

def test_no_tool_name_collisions():
    """Every (spec, op) pair must produce a unique tool name across the registry."""
    seen: dict[str, str] = {}  # tool_name → "domain.name"
    collisions: list[str] = []

    for spec in _specs():
        for op in spec.ops:
            name = tool_name(spec, op)
            owner = f"{spec.domain}.{spec.name}"
            if name in seen and seen[name] != owner:
                collisions.append(
                    f"'{name}' claimed by both '{seen[name]}' and '{owner}'"
                )
            else:
                seen[name] = owner

    assert not collisions, (
        f"Tool name collisions detected in registry:\n"
        + "\n".join(f"  • {c}" for c in collisions)
    )
