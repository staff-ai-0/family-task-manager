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

    _register_legacy_tools()


def _register_legacy_tools() -> None:
    """Migrate the 11 legacy ``jarvis_tools`` capabilities into the registry.

    Each is a data-only EntitySpec wrapping the same app Service the legacy
    handler used. Read-only tools (today/pending/overdue progress) expose only
    the ``list`` op. Idempotent via the _has_spec guards.
    """
    from app.mcp.adapters_tasks import (
        OverdueTasksAdapter,
        PendingApprovalsAdapter,
        TemplateAdapter,
        TodayProgressAdapter,
    )
    from app.mcp.adapters_calendar import EventAdapter
    from app.mcp.adapters_shopping import ItemAdapter as ShoppingItemAdapter
    from app.mcp.adapters_meals import PlanEntryAdapter, RecipeAdapter
    from app.mcp.adapters_notifications import NotificationAdapter
    from app.mcp.adapters_jarvis import ScheduleAdapter
    from app.mcp.schemas.tasks import TemplateCreate, TemplateUpdate
    from app.mcp.schemas.calendar import EventCreate, EventUpdate
    from app.mcp.schemas.shopping import ItemCreate, ItemUpdate
    from app.mcp.schemas.meals import (
        PlanEntryCreate,
        PlanEntryUpdate,
        RecipeCreate,
        RecipeUpdate,
    )
    from app.mcp.schemas.notifications import NotificationCreate
    from app.mcp.schemas.jarvis import ScheduleCreate

    # ── tasks ────────────────────────────────────────────────────────────
    if not _has_spec("tasks", "template"):
        REGISTRY.append(EntitySpec(
            name="template", domain="tasks",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=TemplateCreate, update_schema=TemplateUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=TemplateAdapter(),
            summarize=lambda op, p: f"{op} chore/gig {p.get('title') or p.get('id', '')}",
        ))
    if not _has_spec("tasks", "today"):
        REGISTRY.append(EntitySpec(
            name="today", domain="tasks",
            ops=frozenset({"list"}),
            create_schema=dict, update_schema=dict,
            destructive_ops=frozenset(),
            adapter=TodayProgressAdapter(),
            summarize=lambda op, p: "today's task progress",
        ))
    if not _has_spec("tasks", "pending"):
        REGISTRY.append(EntitySpec(
            name="pending", domain="tasks",
            ops=frozenset({"list"}),
            create_schema=dict, update_schema=dict,
            destructive_ops=frozenset(),
            adapter=PendingApprovalsAdapter(),
            summarize=lambda op, p: "gigs awaiting approval",
        ))
    if not _has_spec("tasks", "overdue"):
        REGISTRY.append(EntitySpec(
            name="overdue", domain="tasks",
            ops=frozenset({"list"}),
            create_schema=dict, update_schema=dict,
            destructive_ops=frozenset(),
            adapter=OverdueTasksAdapter(),
            summarize=lambda op, p: "overdue tasks",
        ))

    # ── calendar ─────────────────────────────────────────────────────────
    if not _has_spec("calendar", "event"):
        REGISTRY.append(EntitySpec(
            name="event", domain="calendar",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=EventCreate, update_schema=EventUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=EventAdapter(),
            summarize=lambda op, p: f"{op} calendar event {p.get('title') or p.get('id', '')}",
        ))

    # ── shopping ─────────────────────────────────────────────────────────
    if not _has_spec("shopping", "item"):
        REGISTRY.append(EntitySpec(
            name="item", domain="shopping",
            ops=frozenset({"list", "create", "update", "delete"}),
            create_schema=ItemCreate, update_schema=ItemUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=ShoppingItemAdapter(),
            summarize=lambda op, p: f"{op} shopping item {p.get('name') or p.get('id', '')}",
        ))

    # ── meals ────────────────────────────────────────────────────────────
    if not _has_spec("meals", "recipe"):
        REGISTRY.append(EntitySpec(
            name="recipe", domain="meals",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=RecipeCreate, update_schema=RecipeUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=RecipeAdapter(),
            summarize=lambda op, p: f"{op} recipe {p.get('name') or p.get('id', '')}",
        ))
    if not _has_spec("meals", "planentry"):
        REGISTRY.append(EntitySpec(
            name="planentry", domain="meals",
            ops=frozenset({"create", "update", "delete"}),
            create_schema=PlanEntryCreate, update_schema=PlanEntryUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=PlanEntryAdapter(),
            summarize=lambda op, p: f"{op} meal plan {p.get('title') or p.get('id', '')}",
        ))

    # ── notifications ────────────────────────────────────────────────────
    if not _has_spec("notifications", "notification"):
        REGISTRY.append(EntitySpec(
            name="notification", domain="notifications",
            ops=frozenset({"list", "get", "create", "delete"}),
            create_schema=NotificationCreate, update_schema=dict,
            destructive_ops=frozenset({"delete"}),
            adapter=NotificationAdapter(),
            summarize=lambda op, p: f"{op} notification {p.get('title') or p.get('id', '')}",
        ))

    # ── jarvis scheduled prompts ─────────────────────────────────────────
    if not _has_spec("jarvis", "schedule"):
        REGISTRY.append(EntitySpec(
            name="schedule", domain="jarvis",
            ops=frozenset({"list", "create", "delete"}),
            create_schema=ScheduleCreate, update_schema=dict,
            destructive_ops=frozenset({"delete"}),
            adapter=ScheduleAdapter(),
            summarize=lambda op, p: f"{op} jarvis schedule {p.get('name') or p.get('id', '')}",
        ))
