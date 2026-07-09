"""Jarvis tool execution — verify each migrated MCP tool runs end-to-end
against real DB fixtures without invoking the LLM.

Post-Task-8: Jarvis sources its tools from the in-memory MCP server. The
legacy ``jarvis_tools`` handlers were migrated to registry adapters, so the
tool names are now ``<domain>_<entity>_<op>`` and ``_execute_tool`` returns
the MCP envelope ``{"ok": bool, "data"|"error": ...}``.
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.calendar_event import CalendarEvent
from app.models.task_template import TaskTemplate
from app.services.jarvis_service import JarvisService


class TestExecuteTool:
    async def test_create_task_template_gig(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "tasks_template_create",
            {
                "title": "Vacuum living room",
                "is_bonus": True,
                "points": 25,
                "interval_days": 7,
                "effort_level": 2,
            },
        )
        assert result["ok"] is True
        assert result["data"]["title"] == "Vacuum living room"
        assert result["data"]["is_bonus"] is True
        assert result["data"]["points"] == 25

        # Verify it landed in the DB
        rows = (
            await db_session.execute(
                select(TaskTemplate).where(TaskTemplate.title == "Vacuum living room")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].effort_level == 2

    async def test_create_task_template_mandatory_keeps_points(
        self, db_session, test_family, test_parent_user
    ):
        # Two-currency economy: mandatory chores DO carry privilege points —
        # the old adapter clamp silently zeroed them.
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "tasks_template_create",
            {"title": "Make bed", "is_bonus": False, "points": 20},
        )
        assert result["ok"] is True
        assert result["data"]["points"] == 20

    async def test_create_calendar_event(
        self, db_session, test_family, test_parent_user
    ):
        start = datetime.now(timezone.utc) + timedelta(days=1)
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "calendar_event_create",
            {
                "title": "Soccer practice",
                "start_iso": start.isoformat(),
                "all_day": False,
                "location": "Field 3",
            },
        )
        assert result["ok"] is True
        assert result["data"]["title"] == "Soccer practice"

        rows = (
            await db_session.execute(
                select(CalendarEvent).where(CalendarEvent.title == "Soccer practice")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].location == "Field 3"
        assert rows[0].source == "manual"

    async def test_create_calendar_event_naive_iso(
        self, db_session, test_family, test_parent_user
    ):
        # Tool must accept naive ISO and treat as UTC.
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "calendar_event_create",
            {"title": "Dentist", "start_iso": "2026-08-12T10:00:00"},
        )
        assert result["ok"] is True

    async def test_list_today_progress_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "tasks_today_list",
            {},
        )
        assert result["ok"] is True
        assert result["data"] == []

    async def test_unknown_tool_returns_error(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "do_evil",
            {},
        )
        assert result["ok"] is False
        assert "unknown tool" in result["error"].lower()

    async def test_create_event_with_bad_iso_returns_error(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "calendar_event_create",
            {"title": "Bad", "start_iso": "not-a-date"},
        )
        assert result["ok"] is False


class TestToolDefinitions:
    async def test_all_tools_have_function_schema(self):
        from app.services.jarvis_service import _mcp_tool_definitions

        defs = await _mcp_tool_definitions()
        assert len(defs) >= 8
        for t in defs:
            assert t["type"] == "function"
            fn = t["function"]
            assert "name" in fn and "description" in fn and "parameters" in fn
            params = fn["parameters"]
            assert params["type"] == "object"
            assert "properties" in params


class TestReadOnlyTools:
    async def test_list_pending_approvals_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "tasks_pending_list", {},
        )
        assert result["ok"] is True
        assert result["data"] == []

    async def test_list_overdue_tasks_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "tasks_overdue_list", {},
        )
        assert result["ok"] is True
        assert result["data"] == []

    async def test_list_recent_notifications_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "notifications_notification_list", {},
        )
        assert result["ok"] is True
        assert result["data"] == []


class TestAddShoppingItem:
    async def test_creates_default_list_when_none(
        self, db_session, test_family, test_parent_user
    ):
        result = await JarvisService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "shopping_item_create", {"name": "Bread", "qty": "1 loaf"},
        )
        assert result["ok"] is True
        assert result["data"]["name"] == "Bread"
        assert result["data"]["list_name"] == "Quick list"

    async def test_appends_to_existing_active_list(
        self, db_session, test_family, test_parent_user
    ):
        from app.schemas.shopping import ShoppingListCreate
        from app.services.shopping_service import ShoppingService
        lst = await ShoppingService.create_list(
            db_session, ShoppingListCreate(name="Costco"),
            test_family.id, test_parent_user.id,
        )
        result = await JarvisService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "shopping_item_create", {"name": "Milk"},
        )
        assert result["ok"] is True
        assert result["data"]["list_name"] == "Costco"
