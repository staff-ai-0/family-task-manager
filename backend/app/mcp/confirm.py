"""Destructive-op classification helpers for the Jarvis HITL gate.

``is_destructive`` decides whether a tool call must be queued as a
``JarvisPendingAction`` rather than executed inline.  ``summarize``
produces the human-readable description stored on the pending-action
row and shown in the frontend confirm card.
"""

from app.mcp.registry import REGISTRY, tool_name, register_builtin


def _ensure_registry() -> None:
    """Guarantee the built-in specs are populated before any look-up.

    ``register_builtin`` is idempotent so calling it here is safe even when
    ``build_server()`` has already run and the specs are already in REGISTRY.
    """
    register_builtin()


def _spec_op(tool: str):
    for spec in REGISTRY:
        for op in spec.ops:
            if tool_name(spec, op) == tool:
                return spec, op
    return None, None


def is_destructive(tool: str) -> bool:
    """Return True iff the tool's op is listed in its spec's destructive_ops."""
    _ensure_registry()
    spec, op = _spec_op(tool)
    return bool(spec and op in spec.destructive_ops)


def summarize(tool: str, args: dict) -> str:
    """Return a human-readable one-liner for the pending-action summary field."""
    _ensure_registry()
    spec, op = _spec_op(tool)
    if spec is None:
        return tool
    return spec.summarize(op, args)
