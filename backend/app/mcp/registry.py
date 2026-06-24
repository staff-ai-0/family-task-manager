from dataclasses import dataclass
from typing import Callable
from pydantic import BaseModel
from app.mcp.adapters import ServiceAdapter


@dataclass(frozen=True)
class EntitySpec:
    name: str
    domain: str
    ops: frozenset[str]
    create_schema: type[BaseModel] | type[dict]
    update_schema: type[BaseModel] | type[dict]
    destructive_ops: frozenset[str]
    adapter: ServiceAdapter
    summarize: Callable[[str, dict], str]


def tool_name(spec: "EntitySpec", op: str) -> str:
    return f"{spec.domain}_{spec.name}_{op}"


REGISTRY: list[EntitySpec] = []


def _has_spec(domain: str, name: str) -> bool:
    return any(s.domain == domain and s.name == name for s in REGISTRY)


def register_builtin() -> None:
    """Append the built-in EntitySpecs to REGISTRY (idempotent).

    Importing the adapter/schema modules here (function-local) avoids an import
    cycle: those modules import the registry's EntitySpec/ServiceAdapter at
    module load. The _has_spec guard makes repeated calls a no-op so re-running
    build_server() never appends duplicate specs.
    """
    from app.mcp.adapters_budget import AccountAdapter
    from app.mcp.schemas.budget import AccountCreate, AccountUpdate

    if not _has_spec("budget", "account"):
        REGISTRY.append(EntitySpec(
            name="account", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=AccountCreate, update_schema=AccountUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=AccountAdapter(),
            summarize=lambda op, p: f"{op} budget account {p.get('name') or p.get('id', '')}",
        ))
