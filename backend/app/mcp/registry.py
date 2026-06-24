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
