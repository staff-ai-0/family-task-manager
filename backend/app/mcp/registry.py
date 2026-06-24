from dataclasses import dataclass, field
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
    # Optional per-op description overrides (keyed by op name).  When an op's
    # key is present the value is used as the MCP tool description instead of
    # the default "{op} {domain}.{name}" string.
    op_descriptions: dict[str, str] = field(default_factory=dict)


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

    _register_budget_rest()
    _register_points_rewards()
    _register_tasks_gigs()
    _register_legacy_tools()


def _register_budget_rest() -> None:
    """Register the remaining 12 budget entities (Phase 5 Task 12)."""
    from app.mcp.adapters_budget_rest import (
        CategoryGroupAdapter,
        CategoryAdapter,
        PayeeAdapter,
        TransactionAdapter,
        AllocationAdapter,
        GoalAdapter,
        RuleAdapter,
        RecurringAdapter,
        TagAdapter,
        SavedFilterAdapter,
        CustomReportAdapter,
        ReceiptDraftAdapter,
    )
    from app.mcp.schemas.budget import (
        CategoryGroupCreate, CategoryGroupUpdate,
        CategoryCreate, CategoryUpdate,
        PayeeCreate, PayeeUpdate,
        TransactionCreate, TransactionUpdate,
        AllocationCreate, AllocationUpdate,
        GoalCreate, GoalUpdate,
        RuleCreate, RuleUpdate,
        RecurringCreate, RecurringUpdate,
        TagCreate, TagUpdate,
        SavedFilterCreate, SavedFilterUpdate,
        CustomReportCreate, CustomReportUpdate,
    )

    if not _has_spec("budget", "category_group"):
        REGISTRY.append(EntitySpec(
            name="category_group", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=CategoryGroupCreate, update_schema=CategoryGroupUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=CategoryGroupAdapter(),
            summarize=lambda op, p: f"{op} budget category_group {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "category"):
        REGISTRY.append(EntitySpec(
            name="category", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=CategoryCreate, update_schema=CategoryUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=CategoryAdapter(),
            summarize=lambda op, p: f"{op} budget category {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "payee"):
        REGISTRY.append(EntitySpec(
            name="payee", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=PayeeCreate, update_schema=PayeeUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=PayeeAdapter(),
            summarize=lambda op, p: f"{op} budget payee {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "transaction"):
        REGISTRY.append(EntitySpec(
            name="transaction", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=TransactionCreate, update_schema=TransactionUpdate,
            destructive_ops=frozenset({"delete", "create", "update"}),
            adapter=TransactionAdapter(),
            summarize=lambda op, p: f"{op} budget transaction amount={p.get('amount')} on {p.get('date') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "allocation"):
        REGISTRY.append(EntitySpec(
            name="allocation", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=AllocationCreate, update_schema=AllocationUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=AllocationAdapter(),
            summarize=lambda op, p: f"{op} budget allocation {p.get('id', '')}",
        ))

    if not _has_spec("budget", "goal"):
        REGISTRY.append(EntitySpec(
            name="goal", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=GoalCreate, update_schema=GoalUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=GoalAdapter(),
            summarize=lambda op, p: f"{op} budget goal {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "rule"):
        REGISTRY.append(EntitySpec(
            name="rule", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=RuleCreate, update_schema=RuleUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=RuleAdapter(),
            summarize=lambda op, p: f"{op} budget categorization rule {p.get('pattern') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "recurring"):
        REGISTRY.append(EntitySpec(
            name="recurring", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=RecurringCreate, update_schema=RecurringUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=RecurringAdapter(),
            summarize=lambda op, p: f"{op} recurring transaction {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "tag"):
        REGISTRY.append(EntitySpec(
            name="tag", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=TagCreate, update_schema=TagUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=TagAdapter(),
            summarize=lambda op, p: f"{op} budget tag {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "saved_filter"):
        REGISTRY.append(EntitySpec(
            name="saved_filter", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=SavedFilterCreate, update_schema=SavedFilterUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=SavedFilterAdapter(),
            summarize=lambda op, p: f"{op} saved filter {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "custom_report"):
        REGISTRY.append(EntitySpec(
            name="custom_report", domain="budget",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=CustomReportCreate, update_schema=CustomReportUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=CustomReportAdapter(),
            summarize=lambda op, p: f"{op} custom report {p.get('name') or p.get('id', '')}",
        ))

    if not _has_spec("budget", "receipt_draft"):
        REGISTRY.append(EntitySpec(
            name="receipt_draft", domain="budget",
            ops=frozenset({"list", "get", "delete"}),
            create_schema=dict, update_schema=dict,
            destructive_ops=frozenset({"delete"}),
            adapter=ReceiptDraftAdapter(),
            summarize=lambda op, p: f"{op} receipt draft {p.get('id', '')}",
        ))


def _register_points_rewards() -> None:
    """Register points + rewards entities (Phase 5 Task 13).

    points:
      - ledger  (list/get; read-only)
      - adjust  (create only; money-moving → destructive)
      - transfer (create only; money-moving → destructive)
    rewards:
      - reward      (LGCUD; delete is destructive)
      - redemption  (list/create; create is money-moving → destructive)
    """
    from app.mcp.adapters_points import LedgerAdapter, AdjustAdapter, TransferAdapter
    from app.mcp.adapters_rewards import RewardAdapter, RedemptionAdapter
    from app.mcp.schemas.points import AdjustCreate, TransferCreate
    from app.mcp.schemas.rewards import RewardCreate, RewardUpdate, RedemptionCreate

    if not _has_spec("points", "ledger"):
        REGISTRY.append(EntitySpec(
            name="ledger", domain="points",
            ops=frozenset({"list", "get"}),
            create_schema=dict, update_schema=dict,
            destructive_ops=frozenset(),
            adapter=LedgerAdapter(),
            summarize=lambda op, p: f"{op} points ledger {p.get('id', '')}",
        ))

    if not _has_spec("points", "adjust"):
        REGISTRY.append(EntitySpec(
            name="adjust", domain="points",
            ops=frozenset({"create"}),
            create_schema=AdjustCreate, update_schema=dict,
            destructive_ops=frozenset({"create"}),
            adapter=AdjustAdapter(),
            summarize=lambda op, p: f"parent adjustment: {p.get('points', '?')} pts for user {p.get('user_id', '')} — {p.get('reason', '')}",
        ))

    if not _has_spec("points", "transfer"):
        REGISTRY.append(EntitySpec(
            name="transfer", domain="points",
            ops=frozenset({"create"}),
            create_schema=TransferCreate, update_schema=dict,
            destructive_ops=frozenset({"create"}),
            adapter=TransferAdapter(),
            summarize=lambda op, p: f"transfer {p.get('points', '?')} pts from {p.get('from_user_id', '')} to {p.get('to_user_id', '')}",
        ))

    if not _has_spec("rewards", "reward"):
        REGISTRY.append(EntitySpec(
            name="reward", domain="rewards",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=RewardCreate, update_schema=RewardUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=RewardAdapter(),
            summarize=lambda op, p: f"{op} reward {p.get('title') or p.get('id', '')}",
        ))

    if not _has_spec("rewards", "redemption"):
        REGISTRY.append(EntitySpec(
            name="redemption", domain="rewards",
            ops=frozenset({"list", "create"}),
            create_schema=RedemptionCreate, update_schema=dict,
            destructive_ops=frozenset({"create"}),
            adapter=RedemptionAdapter(),
            summarize=lambda op, p: f"redeem reward {p.get('reward_id', '')} for user {p.get('user_id', '')}",
        ))


def _register_tasks_gigs() -> None:
    """Register tasks (assignment) + gigs (offering, claim) entities (Phase 5 Task 14).

    tasks:
      - assignment  (LGUD; delete is destructive — no create, assignments come from shuffle)
    gigs:
      - offering  (LGCUD; delete is destructive)
      - claim     (LGUD; delete is destructive — no create, claims come from GigClaimService.claim)
    """
    from app.mcp.adapters_tasks import AssignmentAdapter
    from app.mcp.adapters_gigs import OfferingAdapter, ClaimAdapter
    from app.mcp.schemas.tasks import AssignmentUpdate
    from app.mcp.schemas.gigs import OfferingCreate, OfferingUpdate, ClaimUpdate

    if not _has_spec("tasks", "assignment"):
        REGISTRY.append(EntitySpec(
            name="assignment", domain="tasks",
            ops=frozenset({"list", "get", "update", "delete"}),
            create_schema=dict, update_schema=AssignmentUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=AssignmentAdapter(),
            summarize=lambda op, p: f"{op} task assignment {p.get('id', '')}",
        ))

    if not _has_spec("gigs", "offering"):
        REGISTRY.append(EntitySpec(
            name="offering", domain="gigs",
            ops=frozenset({"list", "get", "create", "update", "delete"}),
            create_schema=OfferingCreate, update_schema=OfferingUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=OfferingAdapter(),
            summarize=lambda op, p: f"{op} gig offering {p.get('title') or p.get('id', '')}",
            op_descriptions={
                "delete": (
                    "soft-delete gigs.offering — sets is_active=False to preserve "
                    "existing claims; the row is retained and can be seen with "
                    "gigs_offering_list (include_inactive=true)"
                ),
            },
        ))

    if not _has_spec("gigs", "claim"):
        REGISTRY.append(EntitySpec(
            name="claim", domain="gigs",
            ops=frozenset({"list", "get", "update", "delete"}),
            create_schema=dict, update_schema=ClaimUpdate,
            destructive_ops=frozenset({"delete"}),
            adapter=ClaimAdapter(),
            summarize=lambda op, p: f"{op} gig claim {p.get('id', '')}",
        ))


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
