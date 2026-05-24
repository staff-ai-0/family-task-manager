"""Frankie tool execution (W6.4) — verify each tool runs end-to-end against
real DB fixtures without invoking the LLM."""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.models.calendar_event import CalendarEvent
from app.models.task_template import TaskTemplate
from app.services.frankie_service import FrankieService


class TestExecuteTool:
    async def test_create_task_template_gig(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "create_task_template",
            {
                "title": "Vacuum living room",
                "is_bonus": True,
                "points": 25,
                "interval_days": 7,
                "effort_level": 2,
            },
        )
        assert result["ok"] is True
        assert result["title"] == "Vacuum living room"
        assert result["is_bonus"] is True
        assert result["points"] == 25

        # Verify it landed in the DB
        rows = (
            await db_session.execute(
                select(TaskTemplate).where(TaskTemplate.title == "Vacuum living room")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].effort_level == 2

    async def test_create_task_template_mandatory_forces_zero_points(
        self, db_session, test_family, test_parent_user
    ):
        # Mandatory + points=20 must be clamped to 0 by the tool wrapper.
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "create_task_template",
            {"title": "Make bed", "is_bonus": False, "points": 20},
        )
        assert result["ok"] is True
        assert result["points"] == 0

    async def test_create_calendar_event(
        self, db_session, test_family, test_parent_user
    ):
        start = datetime.now(timezone.utc) + timedelta(days=1)
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "create_calendar_event",
            {
                "title": "Soccer practice",
                "start_iso": start.isoformat(),
                "all_day": False,
                "location": "Field 3",
            },
        )
        assert result["ok"] is True
        assert result["title"] == "Soccer practice"

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
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "create_calendar_event",
            {"title": "Dentist", "start_iso": "2026-08-12T10:00:00"},
        )
        assert result["ok"] is True

    async def test_list_today_progress_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "list_today_progress",
            {},
        )
        assert result["ok"] is True
        assert "per_member" in result

    async def test_unknown_tool_returns_error(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "do_evil",
            {},
        )
        assert result["ok"] is False
        assert "Unknown tool" in result["error"]

    async def test_create_event_with_bad_iso_returns_error(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session,
            test_family.id,
            test_parent_user.id,
            "create_calendar_event",
            {"title": "Bad", "start_iso": "not-a-date"},
        )
        assert result["ok"] is False


class TestToolDefinitions:
    def test_all_tools_have_function_schema(self):
        from app.services.frankie_service import TOOL_DEFINITIONS
        assert len(TOOL_DEFINITIONS) >= 8
        for t in TOOL_DEFINITIONS:
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
        result = await FrankieService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "list_pending_approvals", {},
        )
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["items"] == []

    async def test_list_overdue_tasks_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "list_overdue_tasks", {},
        )
        assert result["ok"] is True
        assert result["count"] == 0

    async def test_list_recent_notifications_empty(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "list_recent_notifications", {},
        )
        assert result["ok"] is True
        assert result["count"] == 0


class TestAddShoppingItem:
    async def test_creates_default_list_when_none(
        self, db_session, test_family, test_parent_user
    ):
        result = await FrankieService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "add_shopping_item", {"name": "Bread", "qty": "1 loaf"},
        )
        assert result["ok"] is True
        assert result["item_name"] == "Bread"
        assert result["list_name"] == "Quick list"

    async def test_appends_to_existing_active_list(
        self, db_session, test_family, test_parent_user
    ):
        from app.schemas.shopping import ShoppingListCreate
        from app.services.shopping_service import ShoppingService
        lst = await ShoppingService.create_list(
            db_session, ShoppingListCreate(name="Costco"),
            test_family.id, test_parent_user.id,
        )
        result = await FrankieService._execute_tool(
            db_session, test_family.id, test_parent_user.id,
            "add_shopping_item", {"name": "Milk"},
        )
        assert result["ok"] is True
        assert result["list_name"] == "Costco"
