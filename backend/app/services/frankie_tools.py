"""Frankie tool registry (W6.8).

Each tool is a small async handler bundled with its OpenAI-format function
schema. A flat REGISTRY maps tool name → (definition, handler). The chat
service iterates this dict instead of branching on tool name.

Adding a new tool: write a handler + definition below and add the name to
REGISTRY.

Handler contract:
    async def handler(db, family_id, user_id, args: dict) -> dict
Return value must be JSON-serializable. Errors should raise and the chat
service wraps them as ``{"ok": false, "error": "..."}``.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Tuple
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.models.shopping import ShoppingList
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.models.task_template import TaskTemplate
from app.models.user import User


Handler = Callable[[AsyncSession, UUID, UUID, Dict[str, Any]], Awaitable[Dict[str, Any]]]


# ─── Handlers ─────────────────────────────────────────────────────────


async def _create_task_template(db, family_id, user_id, args):
    from app.schemas.task_template import TaskTemplateCreate
    from app.services.task_template_service import TaskTemplateService

    is_bonus = bool(args.get("is_bonus", False))
    points = int(args.get("points", 0))
    if not is_bonus:
        points = 0
    data = TaskTemplateCreate(
        title=str(args["title"])[:200],
        points=points,
        effort_level=int(args.get("effort_level", 1)),
        interval_days=int(args.get("interval_days", 1)),
        is_bonus=is_bonus,
    )
    tmpl = await TaskTemplateService.create_template(db, data, family_id, user_id)
    return {
        "ok": True,
        "template_id": str(tmpl.id),
        "title": tmpl.title,
        "is_bonus": tmpl.is_bonus,
        "points": tmpl.points,
    }


async def _create_calendar_event(db, family_id, user_id, args):
    from app.schemas.calendar_event import CalendarEventCreate
    from app.services.calendar_service import CalendarService

    start = datetime.fromisoformat(args["start_iso"])
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    data = CalendarEventCreate(
        title=str(args["title"])[:200],
        start_ts=start,
        all_day=bool(args.get("all_day", False)),
        location=args.get("location"),
        source="manual",
    )
    evt = await CalendarService.create_event(db, data, family_id, user_id)
    return {
        "ok": True,
        "event_id": str(evt.id),
        "title": evt.title,
        "start_ts": evt.start_ts.isoformat(),
    }


async def _list_today_progress(db, family_id, user_id, args):
    today = date.today()
    q = (
        select(
            TaskAssignment.assigned_to,
            func.count(TaskAssignment.id).label("total"),
            func.count()
            .filter(TaskAssignment.status == AssignmentStatus.COMPLETED)
            .label("done"),
        )
        .where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today,
            )
        )
        .group_by(TaskAssignment.assigned_to)
    )
    rows = (await db.execute(q)).all()
    names = {
        u.id: u.name
        for u in (await db.execute(select(User).where(User.family_id == family_id))).scalars().all()
    }
    return {
        "ok": True,
        "date": today.isoformat(),
        "per_member": [
            {"name": names.get(uid, "?"), "done": int(d or 0), "total": int(t or 0)}
            for uid, t, d in rows
        ],
    }


async def _send_family_notification(db, family_id, user_id, args):
    from app.services.notification_service import NotificationService

    await NotificationService.create(
        db,
        family_id=family_id,
        user_id=None,
        type=NotificationType.SHOPPING_ITEM_ADDED,
        title=str(args["title"])[:200],
        body=args.get("body"),
        link="/notifications",
        push=False,
    )
    return {"ok": True, "sent": True}


async def _list_pending_approvals(db, family_id, user_id, args):
    from app.services.task_assignment_service import TaskAssignmentService

    rows = await TaskAssignmentService.list_pending_approvals(db, family_id)
    names = {
        u.id: u.name
        for u in (await db.execute(select(User).where(User.family_id == family_id))).scalars().all()
    }
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "assignment_id": str(r.id),
                "title": r.template.title if r.template else "",
                "child": names.get(r.assigned_to, "?"),
                "points": r.template.award_points_per_completer if r.template else 0,
                "proof_text": r.proof_text,
                "ai_score": r.ai_validation_score,
            }
            for r in rows
        ],
    }


async def _list_overdue_tasks(db, family_id, user_id, args):
    today = date.today()
    q = (
        select(TaskAssignment)
        .where(
            and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.status == AssignmentStatus.OVERDUE,
                TaskAssignment.assigned_date >= today - timedelta(days=14),
            )
        )
        .order_by(TaskAssignment.assigned_date.desc())
        .limit(50)
    )
    rows = list((await db.execute(q)).scalars().all())
    names = {
        u.id: u.name
        for u in (await db.execute(select(User).where(User.family_id == family_id))).scalars().all()
    }
    tmpl_ids = {r.template_id for r in rows}
    tmpls = {
        t.id: t
        for t in (
            await db.execute(select(TaskTemplate).where(TaskTemplate.id.in_(tmpl_ids)))
        ).scalars().all()
    }
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "title": tmpls.get(r.template_id).title if tmpls.get(r.template_id) else "",
                "child": names.get(r.assigned_to, "?"),
                "assigned_date": r.assigned_date.isoformat(),
            }
            for r in rows
        ],
    }


async def _list_recent_notifications(db, family_id, user_id, args):
    q = (
        select(Notification)
        .where(Notification.family_id == family_id)
        .order_by(Notification.created_at.desc())
        .limit(20)
    )
    rows = list((await db.execute(q)).scalars().all())
    return {
        "ok": True,
        "count": len(rows),
        "items": [
            {
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ],
    }


async def _schedule_frankie_prompt(db, family_id, user_id, args):
    from app.services.frankie_schedule_service import FrankieScheduleService

    s = await FrankieScheduleService.create(
        db,
        family_id=family_id,
        created_by=user_id,
        name=str(args["name"])[:120],
        prompt=str(args["prompt"])[:2000],
        cron_expr=str(args["cron_expr"])[:64],
        channel=str(args.get("channel", "notification")),
    )
    return {
        "ok": True,
        "schedule_id": str(s.id),
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
    }


async def _add_recipe(db, family_id, user_id, args):
    from app.schemas.meal import RecipeCreate
    from app.services.meal_service import MealService

    data = RecipeCreate(
        name=str(args["name"])[:200],
        description=args.get("description"),
        ingredients_text=args.get("ingredients_text"),
        prep_minutes=(int(args["prep_minutes"]) if args.get("prep_minutes") else None),
        source_url=args.get("source_url"),
    )
    r = await MealService.create_recipe(db, data, family_id, user_id)
    return {"ok": True, "recipe_id": str(r.id), "name": r.name}


async def _schedule_meal(db, family_id, user_id, args):
    from app.schemas.meal import MealPlanEntryCreate
    from app.services.meal_service import MealService

    plan_date = date.fromisoformat(args["plan_date"])
    data = MealPlanEntryCreate(
        plan_date=plan_date,
        meal_type=str(args["meal_type"]),
        title=str(args["title"])[:200],
        recipe_id=(UUID(args["recipe_id"]) if args.get("recipe_id") else None),
        notes=args.get("notes"),
    )
    e = await MealService.add_entry(db, data, family_id)
    return {
        "ok": True,
        "entry_id": str(e.id),
        "plan_date": e.plan_date.isoformat(),
        "meal_type": e.meal_type,
    }


async def _add_shopping_item(db, family_id, user_id, args):
    from app.schemas.shopping import ShoppingItemCreate, ShoppingListCreate
    from app.services.shopping_service import ShoppingService

    lst_q = (
        select(ShoppingList)
        .where(
            and_(
                ShoppingList.family_id == family_id,
                ShoppingList.is_archived.is_(False),
            )
        )
        .order_by(ShoppingList.updated_at.desc())
        .limit(1)
    )
    lst = (await db.execute(lst_q)).scalar_one_or_none()
    if lst is None:
        lst = await ShoppingService.create_list(
            db, ShoppingListCreate(name="Quick list"), family_id, user_id,
        )
    item = await ShoppingService.add_item(
        db,
        list_id=lst.id,
        family_id=family_id,
        added_by=user_id,
        data=ShoppingItemCreate(
            name=str(args["name"])[:200],
            qty=args.get("qty"),
        ),
    )
    return {
        "ok": True,
        "list_name": lst.name,
        "item_id": str(item.id),
        "item_name": item.name,
    }


# ─── Schemas ──────────────────────────────────────────────────────────


_DEF_CREATE_TASK = {
    "type": "function",
    "function": {
        "name": "create_task_template",
        "description": (
            "Create a new recurring chore (mandatory, points=0) or gig "
            "(bonus, awards points). Use when parent asks to add a chore."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short task title."},
                "is_bonus": {
                    "type": "boolean",
                    "description": "True = gig (awards points), False = mandatory chore (no points).",
                },
                "points": {
                    "type": "integer",
                    "description": "Points awarded (only used when is_bonus=true). Use 0 for mandatory.",
                    "default": 0,
                },
                "interval_days": {
                    "type": "integer",
                    "description": "Frequency: 1=daily, 7=weekly, 2-6=every N days.",
                    "default": 1,
                },
                "effort_level": {
                    "type": "integer",
                    "description": "1=easy ×1.0, 2=medium ×1.5, 3=hard ×2.0",
                    "default": 1,
                },
            },
            "required": ["title", "is_bonus"],
        },
    },
}

_DEF_CREATE_EVENT = {
    "type": "function",
    "function": {
        "name": "create_calendar_event",
        "description": "Add a one-off event to the family calendar.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_iso": {
                    "type": "string",
                    "description": "ISO-8601 timestamp, e.g. 2026-06-01T15:00:00",
                },
                "all_day": {"type": "boolean", "default": False},
                "location": {"type": "string"},
            },
            "required": ["title", "start_iso"],
        },
    },
}

_DEF_TODAY = {
    "type": "function",
    "function": {
        "name": "list_today_progress",
        "description": "Get today's per-member task progress summary.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_NOTIFY = {
    "type": "function",
    "function": {
        "name": "send_family_notification",
        "description": (
            "Post a family-wide in-app notification. Use sparingly — only "
            "when the parent explicitly asks to remind everyone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title"],
        },
    },
}

_DEF_PENDING = {
    "type": "function",
    "function": {
        "name": "list_pending_approvals",
        "description": (
            "List gigs awaiting parent approval. Use when parent asks "
            "what's queued for review."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_OVERDUE = {
    "type": "function",
    "function": {
        "name": "list_overdue_tasks",
        "description": "List overdue task assignments across the family.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_RECENT_NOTIFS = {
    "type": "function",
    "function": {
        "name": "list_recent_notifications",
        "description": "Last 20 in-app notifications for the family.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_DEF_ADD_SHOPPING = {
    "type": "function",
    "function": {
        "name": "add_shopping_item",
        "description": (
            "Add an item to the family's most recent active shopping list, "
            "or create a list named 'Quick list' if none exists."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "qty": {"type": "string"},
            },
            "required": ["name"],
        },
    },
}


_DEF_ADD_RECIPE = {
    "type": "function",
    "function": {
        "name": "add_recipe",
        "description": "Save a recipe to the family cookbook for later use in meal plans.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "ingredients_text": {"type": "string"},
                "prep_minutes": {"type": "integer"},
                "source_url": {"type": "string"},
            },
            "required": ["name"],
        },
    },
}

_DEF_SCHEDULE_MEAL = {
    "type": "function",
    "function": {
        "name": "schedule_meal",
        "description": (
            "Add a meal to the plan for a specific date + meal type. Use "
            "after the parent confirms the dish or after add_recipe."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "plan_date": {"type": "string", "description": "YYYY-MM-DD"},
                "meal_type": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                },
                "title": {"type": "string"},
                "recipe_id": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["plan_date", "meal_type", "title"],
        },
    },
}


_DEF_SCHEDULE_FRANKIE = {
    "type": "function",
    "function": {
        "name": "schedule_frankie_prompt",
        "description": (
            "Set up a recurring Jarvis prompt that runs on a cron schedule "
            "(e.g. 'weekly Sunday summary at 6pm'). Output goes to the "
            "in-app notifications feed (or chat channel)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short label."},
                "prompt": {
                    "type": "string",
                    "description": "Prompt Jarvis will answer each run.",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "5-field cron: 'minute hour day month dow' (e.g. '0 18 * * 0' = Sun 6pm).",
                },
                "channel": {
                    "type": "string",
                    "enum": ["notification", "chat"],
                    "default": "notification",
                },
            },
            "required": ["name", "prompt", "cron_expr"],
        },
    },
}


REGISTRY: Dict[str, Tuple[dict, Handler]] = {
    "create_task_template":      (_DEF_CREATE_TASK,    _create_task_template),
    "create_calendar_event":     (_DEF_CREATE_EVENT,   _create_calendar_event),
    "list_today_progress":       (_DEF_TODAY,          _list_today_progress),
    "send_family_notification":  (_DEF_NOTIFY,         _send_family_notification),
    "list_pending_approvals":    (_DEF_PENDING,        _list_pending_approvals),
    "list_overdue_tasks":        (_DEF_OVERDUE,        _list_overdue_tasks),
    "list_recent_notifications": (_DEF_RECENT_NOTIFS,  _list_recent_notifications),
    "add_shopping_item":         (_DEF_ADD_SHOPPING,   _add_shopping_item),
    "add_recipe":                (_DEF_ADD_RECIPE,     _add_recipe),
    "schedule_meal":             (_DEF_SCHEDULE_MEAL,  _schedule_meal),
    "schedule_frankie_prompt":   (_DEF_SCHEDULE_FRANKIE, _schedule_frankie_prompt),
}


def tool_definitions() -> list[dict]:
    """Return the OpenAI-format tool list in registration order."""
    return [defn for defn, _ in REGISTRY.values()]


async def dispatch(
    db: AsyncSession,
    family_id: UUID,
    user_id: UUID,
    name: str,
    args: dict,
) -> dict:
    """Invoke the handler for ``name``. Wraps exceptions as error dicts."""
    if name not in REGISTRY:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    _, handler = REGISTRY[name]
    try:
        return await handler(db, family_id, user_id, args or {})
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
