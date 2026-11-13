"""Chore rules v2 pure rules: cutoff + weekly ladder."""
from datetime import date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as AS
from app.services.early_bird_rules import (
    CoveredRow, EarlyBirdConfig, LadderResult, completed_in_time, day_times,
    done_early, week_ladder,
)

MX = ZoneInfo("America/Mexico_City")
MON = date(2026, 11, 2)


def cfg():
    return EarlyBirdConfig(
        enabled=True, enabled_at=datetime(2026, 10, 1, tzinfo=MX), deadline=time(11, 0),
        days=None, bonus_pct=20, week_pct=5, streak_cents=5000, tz=MX,
        cutoff=time(20, 30), grab_end=time(22, 30),
    )


def at(h, m=0, s=0):
    return datetime(MON.year, MON.month, MON.day, h, m, s, tzinfo=MX)


def row(completed_at, status=AS.COMPLETED, approval=AP.NONE, grade=None, parent_marked=False):
    return CoveredRow(uuid4(), MON, status, approval, grade, completed_at,
                      parent_marked=parent_marked)


def test_day_times_has_cutoff_and_grab_end():
    t = day_times(cfg(), MON)
    assert t.cutoff == at(20, 30)
    assert t.grab_end == at(22, 30)


def test_completed_in_time_boundary():
    assert completed_in_time(row(at(20, 29, 59)), cfg())
    assert not completed_in_time(row(at(20, 30)), cfg())
    assert not completed_in_time(row(None), cfg())


def test_completed_in_time_grade_and_approval():
    assert not completed_in_time(row(at(9), grade="missed"), cfg())
    assert not completed_in_time(row(at(9), grade="partial"), cfg())
    assert not completed_in_time(row(at(9), status=AS.PENDING), cfg())
    assert not completed_in_time(row(at(9), approval=AP.PENDING), cfg())
    assert completed_in_time(row(at(9), approval=AP.PENDING), cfg(), grace=True)
    assert completed_in_time(row(at(9), approval=AP.APPROVED), cfg())
    assert not completed_in_time(row(at(9), approval=AP.REJECTED), cfg())


def test_parent_marked_counts_after_cutoff():
    late = at(23, 0)
    assert completed_in_time(row(late, approval=AP.APPROVED, parent_marked=True), cfg())
    assert not completed_in_time(row(late, approval=AP.APPROVED, parent_marked=False), cfg())
    # still subject to approval and grade
    assert not completed_in_time(row(late, approval=AP.PENDING, parent_marked=True), cfg())
    assert completed_in_time(row(late, approval=AP.PENDING, parent_marked=True), cfg(), grace=True)
    assert not completed_in_time(row(late, approval=AP.APPROVED, grade="missed", parent_marked=True), cfg())


def test_done_early_uses_deadline_not_r1():
    assert done_early(row(at(10, 59)), cfg())
    assert done_early(row(at(10, 30)), cfg())  # after R1 (10:00) still early
    assert not done_early(row(at(11, 0)), cfg())
    assert not done_early(row(at(10, 0), grade="missed"), cfg())


@pytest.mark.parametrize("c,e,t,tier,pct", [
    (0, 0, 0, "neutral", 0),
    (5, 0, 10, "no_pay", 0),
    (6, 0, 10, "per_task", 0),
    (59, 59, 60, "per_task", 0),
    (9, 9, 10, "per_task", 0),
    (10, 8, 10, "bonus", 5),
    (10, 9, 10, "bonus", 10),
    (10, 10, 10, "bonus", 15),
    (10, 7, 10, "bonus", 0),
])
def test_week_ladder(c, e, t, tier, pct):
    r = week_ladder(c, e, t)
    assert r == LadderResult(tier=tier, bonus_pct=pct, completed=c, early=e, total=t)
