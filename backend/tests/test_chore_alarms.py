"""Chore rules v2, Task 6: two teen alarms a day (15:00 / 19:00 family-local)."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.notification import Notification
from app.models.task_assignment import AssignmentStatus
from app.models.user import UserRole
from app.services.early_bird_rules import EarlyBirdConfig, alarm_slot
from app.services.early_bird_service import EarlyBirdService
from tests.test_early_bird_sweep import (
    MX, _assign, _at, _rows, _setup, _today, _tpl, _user,
)


def _cfg(**kw):
    base = dict(enabled=True, enabled_at=datetime(2026, 10, 1, tzinfo=MX), deadline=time(11, 0),
                days=None, bonus_pct=20, week_pct=5, streak_cents=5000, tz=MX,
                cutoff=time(20, 30), grab_end=time(22, 30),
                alarm_1=time(15, 0), alarm_2=time(19, 0))
    base.update(kw)
    return EarlyBirdConfig(**base)


def _local(h, m, s=0, day=datetime(2026, 11, 4)):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=MX)


def test_slot_windows():
    """30 minutes from each alarm time, so a late or missed */5 tick still
    sends that day's alarm (the send record dedupes inside the window)."""
    c = _cfg()
    assert alarm_slot(c, _local(15, 0, 0)) == "a1"
    assert alarm_slot(c, _local(15, 5, 0)) == "a1"
    assert alarm_slot(c, _local(15, 29, 59)) == "a1"
    assert alarm_slot(c, _local(15, 30, 0)) is None
    assert alarm_slot(c, _local(14, 59, 59)) is None
    assert alarm_slot(c, _local(19, 0, 0)) == "a2"
    assert alarm_slot(c, _local(19, 29, 59)) == "a2"
    assert alarm_slot(c, _local(19, 30, 0)) is None


def test_slot_window_never_runs_past_the_cutoff():
    """An alarm 15 min before the cutoff must not fire after it: by then the
    chores are no longer the teen's ("due by 20:30" would be false)."""
    c = _cfg(alarm_2=time(20, 15))
    assert alarm_slot(c, _local(20, 29, 59)) == "a2"
    assert alarm_slot(c, _local(20, 30, 0)) is None
    assert alarm_slot(c, _local(20, 40, 0)) is None


def test_overlapping_windows_pick_the_later_alarm():
    """Alarms 10 min apart: once the second has started it is the live slot,
    so its own send record (since its start) decides — not the first's."""
    c = _cfg(alarm_1=time(15, 0), alarm_2=time(15, 10))
    assert alarm_slot(c, _local(15, 5)) == "a1"
    assert alarm_slot(c, _local(15, 12)) == "a2"
    assert alarm_slot(c, _local(15, 35)) == "a2"
    assert alarm_slot(c, _local(15, 40)) is None


def test_slot_uses_family_tz_from_utc():
    c = _cfg()
    utc = _local(15, 2).astimezone(timezone.utc)
    assert alarm_slot(c, utc) == "a1"


def test_slot_inactive_day():
    wed = datetime(2026, 11, 4).date().weekday()
    c = _cfg(days=frozenset({d for d in range(7) if d != wed}))
    assert alarm_slot(c, _local(15, 0)) is None


@pytest.fixture
async def ctx(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    tpl = await _tpl(db_session, test_family)
    await _assign(db_session, test_teen_user, tpl, _today())
    return db_session, test_family, test_teen_user, tpl, _today()


async def test_teen_with_pending_gets_alarm(ctx):
    db, fam, teen, tpl, day = ctx
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    assert res["alarms"] == 1
    rows = await _rows(db, teen, "chore_alarm")
    assert len(rows) == 1
    assert rows[0].expires_at.astimezone(MX) == datetime.combine(day, time(20, 30), tzinfo=MX)
    assert "20:30" in rows[0].body
    assert "1 tarea" in rows[0].body or "1 chore" in rows[0].body


async def test_non_teens_and_empty_teens_get_nothing(ctx):
    db, fam, teen, tpl, day = ctx
    kid = await _user(db, fam, "Kid", UserRole.CHILD)
    par = await _user(db, fam, "Par", UserRole.PARENT)
    free = await _user(db, fam, "Free", UserRole.TEEN)
    await _assign(db, kid, tpl, day)
    await _assign(db, par, tpl, day)
    await _assign(db, free, tpl, day, status=AssignmentStatus.COMPLETED)
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    assert res["alarms"] == 1
    for u in (kid, par, free):
        assert await _rows(db, u, "chore_alarm") == []


async def test_other_family_teen_not_alarmed(ctx, db_session):
    from app.models.family import Family
    db, fam, teen, tpl, day = ctx
    other = Family(name="Other", timezone="America/Mexico_City")
    db.add(other)
    await db.commit()
    stranger = await _user(db, other, "Stranger", UserRole.TEEN)
    otpl = await _tpl(db, other)
    await _assign(db, stranger, otpl, day)
    await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    assert await _rows(db, stranger, "chore_alarm") == []


async def test_same_slot_twice_sends_once(ctx):
    db, fam, teen, tpl, day = ctx
    await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    # Real clock is far from the injected instant; pin the row into the slot.
    from tests.test_early_bird_sweep import _stamp
    await _stamp(db, _at(day, 15, 0))
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 15, 3))
    assert res["alarms"] == 0
    assert len(await _rows(db, teen, "chore_alarm")) == 1


async def test_second_alarm_not_suppressed_by_first(ctx):
    db, fam, teen, tpl, day = ctx
    await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    from tests.test_early_bird_sweep import _stamp
    await _stamp(db, _at(day, 15, 0))
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 19, 0))
    assert res["alarms"] == 1
    assert len(await _rows(db, teen, "chore_alarm")) == 2


async def test_early_bird_off_no_alarm(ctx):
    db, fam, teen, tpl, day = ctx
    fam.early_bird_enabled = False
    await db.commit()
    res = await EarlyBirdService.run_sweep(db, now=_at(day, 15, 0))
    assert res["alarms"] == 0
    assert await _rows(db, teen, "chore_alarm") == []


async def test_copy_es_en_singular_plural():
    from app.services.notification_service import _COPY as C
    for key, es, en in (
        ("chore_alarm_one", "Te falta 1 tarea hoy", "1 chore left today"),
        ("chore_alarm", "Te faltan {n} tareas hoy", "{n} chores left today"),
    ):
        text = C[key]
        blob_es = (text["title"]["es"] + " " + (text["body"] or {}).get("es", ""))
        blob_en = (text["title"]["en"] + " " + (text["body"] or {}).get("en", ""))
        assert es in blob_es and en in blob_en
        assert "{cutoff}" in blob_es and "{cutoff}" in blob_en


async def test_late_tick_still_sends_once_per_slot(ctx):
    """The 15:00 tick was missed: 15:20 sends, 15:25 (same slot) and 15:31
    (window over) send nothing, and the 19:00 slot is independent."""
    from tests.test_early_bird_sweep import _stamp
    db, fam, teen, tpl, day = ctx
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 15, 20)))["alarms"] == 1
    await _stamp(db, _at(day, 15, 20))
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 15, 25)))["alarms"] == 0
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 15, 31)))["alarms"] == 0
    assert len(await _rows(db, teen, "chore_alarm")) == 1
    assert (await EarlyBirdService.run_sweep(db, now=_at(day, 19, 0)))["alarms"] == 1
    assert len(await _rows(db, teen, "chore_alarm")) == 2
