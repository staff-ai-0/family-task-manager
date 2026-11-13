"""Chore rules v2 (Task 2b): the deadline (11:00) is the one early time."""
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as AS
from app.services.early_bird_rules import (
    CoveredRow, EarlyBirdConfig, chore_state, done_early,
)
from app.services.early_bird_service import EarlyBirdService
from tests.test_early_bird_bonus import (
    _assign, _bonus_rows, _complete, _local, _past_wednesday, _setup, _template,
)

MX = ZoneInfo("America/Mexico_City")
MON = date(2026, 11, 2)
SUN = date(2026, 11, 8)


def cfg():
    return EarlyBirdConfig(
        enabled=True, enabled_at=datetime(2026, 10, 1, tzinfo=MX), deadline=time(11, 0),
        days=None, bonus_pct=20, week_pct=5, streak_cents=5000, tz=MX,
        cutoff=time(20, 30), grab_end=time(22, 30), alarm_1=time(15, 0), alarm_2=time(19, 0))


def at(h, m=0, s=0, day=MON):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=MX)


def row(completed_at, **kw):
    return CoveredRow(uuid4(), MON, AS.COMPLETED, AP.NONE, None, completed_at, **kw)


def _week_rows(n):
    return [
        CoveredRow(uuid4(), MON + timedelta(days=i), AS.COMPLETED, AP.NONE, None,
                   at(10, 30, day=MON + timedelta(days=i)))
        for i in range(n)
    ]


def test_chore_state_boundary_is_eleven():
    c = cfg()
    assert chore_state(row(at(10, 59, 59)), c, at(12)) == "early"
    assert chore_state(row(at(10, 0, 0)), c, at(12)) == "early"
    assert chore_state(row(at(11, 0, 0)), c, at(12)) == "missed"


def test_open_until_deadline():
    c = cfg()
    r = CoveredRow(uuid4(), MON, AS.PENDING, AP.NONE, None, None)
    assert chore_state(r, c, at(10, 30)) == "open"
    assert chore_state(r, c, at(11, 0)) == "missed"


def test_done_early_false_when_parent_marked():
    c = cfg()
    assert done_early(row(at(9)), c) is True
    assert done_early(row(at(9), parent_marked=True), c) is False


def test_week_over_flips_at_sunday_eleven():
    c = cfg()
    rows = _week_rows(7)
    assert EarlyBirdService._week_from_rows(c, rows, MON, at(10, 30, day=SUN))[0] == "in_progress"
    assert EarlyBirdService._week_from_rows(c, rows, MON, at(11, 0, day=SUN))[0] == "early"


def test_week_early_when_each_day_done_at_1030():
    c = cfg()
    assert EarlyBirdService._week_from_rows(c, _week_rows(6), MON, at(12, day=SUN))[0] == "early"


async def test_bonus_at_1030_not_at_1100(db_session, test_family, test_teen_user):
    await _setup(db_session, test_family)
    day = _past_wednesday()
    t = await _template(db_session, test_family)
    a = await _assign(db_session, test_teen_user, t, day)
    await _complete(db_session, a, test_teen_user, _local(day, 10, 30))
    assert len(await _bonus_rows(db_session, test_teen_user)) == 1
    b = await _assign(db_session, test_teen_user, t, day)
    await _complete(db_session, b, test_teen_user, _local(day, 11, 0))
    assert len(await _bonus_rows(db_session, test_teen_user)) == 1
