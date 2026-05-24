"""W9.1-W9.4 cross-feature tests."""

import pytest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import select

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.calendar_event import CalendarEvent
from app.models.frankie_schedule import FrankieSchedule
from app.models.dm import DMThread, DMMessage
from app.schemas.calendar_event import CalendarEventCreate
from app.services.calendar_service import CalendarService, _expand_recurrence
from app.services.dm_service import DMService
from app.services.frankie_schedule_service import (
    FrankieScheduleService,
    _parse_cron,
    _next_fire,
)


# ─── W9.1 Frankie schedules ────────────────────────────────────────────


class TestFrankieSchedule:
    def test_parse_valid_cron(self):
        t = _parse_cron("0 9 * * 1")
        nxt = _next_fire(t, datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert nxt.weekday() == 0  # Monday

    def test_parse_invalid_cron(self):
        with pytest.raises(ValidationException):
            _parse_cron("bogus")
        with pytest.raises(ValidationException):
            _parse_cron("0 9 * *")  # only 4 fields

    async def test_create_schedule_sets_next_run(
        self, db_session, test_family, test_parent_user
    ):
        s = await FrankieScheduleService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            name="Weekly summary",
            prompt="Give me a weekly summary",
            cron_expr="0 18 * * 0",
        )
        assert s.is_active is True
        assert s.next_run_at is not None
        assert s.next_run_at > datetime.now(timezone.utc)

    async def test_invalid_channel_rejected(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(ValidationException):
            await FrankieScheduleService.create(
                db_session,
                family_id=test_family.id,
                created_by=test_parent_user.id,
                name="x",
                prompt="x",
                cron_expr="0 9 * * 1",
                channel="email",
            )

    async def test_toggle_flips_active(
        self, db_session, test_family, test_parent_user
    ):
        s = await FrankieScheduleService.create(
            db_session,
            family_id=test_family.id,
            created_by=test_parent_user.id,
            name="x", prompt="x", cron_expr="0 9 * * 1",
        )
        toggled = await FrankieScheduleService.toggle(
            db_session, s.id, test_family.id
        )
        assert toggled.is_active is False
        toggled = await FrankieScheduleService.toggle(
            db_session, s.id, test_family.id
        )
        assert toggled.is_active is True


# ─── W9.2 Recurring calendar ──────────────────────────────────────────


class TestRecurrence:
    async def test_weekly_recurrence_expands(
        self, db_session, test_family, test_parent_user
    ):
        start = datetime(2026, 6, 1, 15, 0, tzinfo=timezone.utc)  # Monday
        await CalendarService.create_event(
            db_session,
            CalendarEventCreate(
                title="Soccer practice",
                start_ts=start,
                source="manual",
                recurrence_rule="FREQ=WEEKLY;COUNT=4",
            ),
            test_family.id,
            test_parent_user.id,
        )
        rows = await CalendarService.list_events(
            db_session, test_family.id,
            start=start, end=start + timedelta(days=30),
        )
        soccer = [r for r in rows if r.title == "Soccer practice"]
        assert len(soccer) == 4

    async def test_invalid_rrule_rejected(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(ValidationException):
            await CalendarService.create_event(
                db_session,
                CalendarEventCreate(
                    title="Bad",
                    start_ts=datetime.now(timezone.utc),
                    source="manual",
                    recurrence_rule="not a valid rrule",
                ),
                test_family.id,
                test_parent_user.id,
            )

    async def test_non_recurring_unchanged(
        self, db_session, test_family, test_parent_user
    ):
        start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
        await CalendarService.create_event(
            db_session,
            CalendarEventCreate(title="One-off", start_ts=start, source="manual"),
            test_family.id,
            test_parent_user.id,
        )
        rows = await CalendarService.list_events(
            db_session, test_family.id,
            start=start - timedelta(days=1),
            end=start + timedelta(days=1),
        )
        titles = [r.title for r in rows]
        assert titles.count("One-off") == 1


# ─── W9.3 DM ──────────────────────────────────────────────────────────


class TestDM:
    async def test_create_thread_dedup(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        t1 = await DMService.create_thread(
            db_session, test_family.id, test_parent_user.id,
            [test_child_user.id],
        )
        t2 = await DMService.create_thread(
            db_session, test_family.id, test_parent_user.id,
            [test_child_user.id],
        )
        assert t1.id == t2.id  # dedup'd

    async def test_thread_needs_two_participants(
        self, db_session, test_family, test_parent_user
    ):
        with pytest.raises(ValidationException):
            await DMService.create_thread(
                db_session, test_family.id, test_parent_user.id, []
            )

    async def test_cross_family_participant_rejected(
        self, db_session, test_family, test_parent_user
    ):
        from uuid import uuid4
        with pytest.raises(ForbiddenException):
            await DMService.create_thread(
                db_session, test_family.id, test_parent_user.id, [uuid4()]
            )

    async def test_non_participant_cannot_read(
        self, db_session, test_family, test_parent_user, test_child_user,
        test_teen_user,
    ):
        t = await DMService.create_thread(
            db_session, test_family.id, test_parent_user.id,
            [test_child_user.id],
        )
        with pytest.raises(ForbiddenException):
            await DMService.list_messages(
                db_session, t.id, test_teen_user.id, test_family.id
            )

    async def test_post_and_read(
        self, db_session, test_family, test_parent_user, test_child_user
    ):
        t = await DMService.create_thread(
            db_session, test_family.id, test_parent_user.id,
            [test_child_user.id],
        )
        await DMService.post_message(
            db_session, t.id, test_parent_user.id, test_family.id, "hello kid"
        )
        msgs = await DMService.list_messages(
            db_session, t.id, test_child_user.id, test_family.id
        )
        assert len(msgs) == 1
        assert msgs[0].body == "hello kid"


# ─── W9.4 Stripe ──────────────────────────────────────────────────────


class TestStripe:
    def test_not_configured_by_default(self, monkeypatch):
        from app.core import config
        from app.services.stripe_service import StripeService

        monkeypatch.setattr(config.settings, "STRIPE_SECRET_KEY", "")
        assert StripeService.is_configured() is False

    def test_price_lookup_missing_setting(self, monkeypatch):
        from app.core import config
        from app.services.stripe_service import StripeService

        monkeypatch.setattr(config.settings, "STRIPE_PRICE_PLUS_MONTHLY", "")
        with pytest.raises(ValidationException):
            StripeService.price_for("plus", "monthly")

    def test_price_lookup_invalid_combo(self):
        from app.services.stripe_service import StripeService

        with pytest.raises(ValidationException):
            StripeService.price_for("ultra", "monthly")
