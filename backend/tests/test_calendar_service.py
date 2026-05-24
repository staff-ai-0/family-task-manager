"""CalendarService tests (W2.1)."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.exceptions import NotFoundException, ValidationException
from app.schemas.calendar_event import CalendarEventCreate, CalendarEventUpdate
from app.services.calendar_service import CalendarService


def _make_create(title="Soccer", offset_hours=24, source="manual"):
    start = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return CalendarEventCreate(title=title, start_ts=start, source=source)


class TestCalendarCRUD:
    async def test_create_event(
        self, db_session, test_family, test_parent_user
    ):
        data = _make_create()
        evt = await CalendarService.create_event(
            db_session, data, test_family.id, test_parent_user.id
        )
        assert evt.title == "Soccer"
        assert evt.family_id == test_family.id
        assert evt.source == "manual"

    async def test_create_rejects_end_before_start(
        self, db_session, test_family, test_parent_user
    ):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        end = start - timedelta(hours=1)
        bad = CalendarEventCreate(
            title="Bad", start_ts=start, end_ts=end, source="manual"
        )
        with pytest.raises(ValidationException):
            await CalendarService.create_event(
                db_session, bad, test_family.id, test_parent_user.id
            )

    async def test_get_event_isolation(
        self, db_session, test_family, test_parent_user
    ):
        evt = await CalendarService.create_event(
            db_session, _make_create(), test_family.id, test_parent_user.id
        )
        with pytest.raises(NotFoundException):
            await CalendarService.get_event(db_session, evt.id, uuid4())

    async def test_list_range_filter(
        self, db_session, test_family, test_parent_user
    ):
        now = datetime.now(timezone.utc)
        await CalendarService.create_event(
            db_session,
            _make_create("Near", offset_hours=2),
            test_family.id,
            test_parent_user.id,
        )
        await CalendarService.create_event(
            db_session,
            _make_create("Far", offset_hours=24 * 90),
            test_family.id,
            test_parent_user.id,
        )
        rows = await CalendarService.list_events(
            db_session,
            test_family.id,
            start=now,
            end=now + timedelta(days=7),
        )
        titles = [r.title for r in rows]
        assert "Near" in titles
        assert "Far" not in titles

    async def test_update_event(
        self, db_session, test_family, test_parent_user
    ):
        evt = await CalendarService.create_event(
            db_session, _make_create(), test_family.id, test_parent_user.id
        )
        updated = await CalendarService.update_event(
            db_session,
            evt.id,
            CalendarEventUpdate(title="Renamed", location="Field 3"),
            test_family.id,
        )
        assert updated.title == "Renamed"
        assert updated.location == "Field 3"

    async def test_delete_event(
        self, db_session, test_family, test_parent_user
    ):
        evt = await CalendarService.create_event(
            db_session, _make_create(), test_family.id, test_parent_user.id
        )
        await CalendarService.delete_event(db_session, evt.id, test_family.id)
        with pytest.raises(NotFoundException):
            await CalendarService.get_event(db_session, evt.id, test_family.id)

    async def test_invalid_source_rejected(self):
        start = datetime.now(timezone.utc) + timedelta(hours=1)
        with pytest.raises(Exception):
            CalendarEventCreate(title="X", start_ts=start, source="bogus")
