"""Early Bird pure rules — no DB, no fixtures."""
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as AS
from app.services.early_bird_rules import (
    GRABS_PUSH_WINDOW, PENDING_GRACE_DAYS, R1_BEFORE, R2_BEFORE, SETTLE_LOOKBACK_WEEKS,
    STREAK_WEEKS, CoveredRow, EarlyBirdConfig, chore_state, day_result, day_times,
    early_bonus_points, is_active_day, next_run, pays_streak, reminder_stage,
    week_bonus, week_eligible, week_result,
)

MX = ZoneInfo("America/Mexico_City")
MON = date(2026, 11, 2)   # Monday
SAT = date(2026, 11, 7)   # Saturday


def cfg(**kw):
    base = dict(enabled=True, enabled_at=datetime(2026, 10, 1, tzinfo=MX), deadline=time(11, 0),
                days=None, bonus_pct=20, week_pct=5, streak_cents=5000, tz=MX,
                cutoff=time(20, 30), grab_end=time(22, 30))
    base.update(kw)
    return EarlyBirdConfig(**base)


def row(status=AS.COMPLETED, approval=AP.NONE, grade=None, completed_at=None, d=MON):
    return CoveredRow(uuid4(), d, status, approval, grade, completed_at)


def at(h, m=0, s=0, day=MON):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=MX)


def test_constants():
    assert STREAK_WEEKS == 3
    assert R1_BEFORE == timedelta(minutes=60)
    assert R2_BEFORE == timedelta(minutes=30)
    assert GRABS_PUSH_WINDOW == timedelta(minutes=60)
    assert SETTLE_LOOKBACK_WEEKS == 3
    assert PENDING_GRACE_DAYS == 7


def test_from_family():
    fam = SimpleNamespace(early_bird_enabled=True, early_bird_enabled_at=None,
                          early_bird_deadline=time(11), early_bird_days=[0, 2],
                          early_bird_bonus_pct=20, early_bird_week_pct=5,
                          early_bird_streak_cents=100, timezone="America/Mexico_City",
                          chore_cutoff=time(20, 30), grab_window_end=time(22, 30))
    c = EarlyBirdConfig.from_family(fam)
    assert c.days == frozenset({0, 2}) and c.tz == MX and c.enabled_at is None
    fam.early_bird_days = None
    fam.timezone = "Nope/Bad"
    c = EarlyBirdConfig.from_family(fam)
    assert c.days is None and c.tz == ZoneInfo("UTC")


def test_day_times_mexico():
    t = day_times(cfg(), MON)
    assert t.deadline == at(11) and t.r1 == at(10) and t.r2 == at(10, 30)
    assert t.r1.tzinfo is not None and t.r1.utcoffset() == at(10).utcoffset()


def test_is_active_day():
    assert is_active_day(cfg(), MON)
    assert not is_active_day(cfg(days=frozenset({0, 1, 2, 3, 4})), SAT)
    assert is_active_day(cfg(days=frozenset({5})), SAT)
    assert not is_active_day(cfg(enabled=False), MON)
    assert not is_active_day(cfg(enabled_at=None), MON)
    assert not is_active_day(cfg(enabled_at=at(10)), MON)       # r1 == enabled_at
    assert is_active_day(cfg(enabled_at=at(9, 59)), MON)


def test_week_eligible():
    assert week_eligible(cfg(), MON)
    assert not week_eligible(cfg(enabled_at=at(10, 0, 1)), MON)
    assert not week_eligible(cfg(enabled=False), MON)
    assert not week_eligible(cfg(enabled_at=None), MON)


def test_chore_state_boundary():
    c = cfg()
    now = at(12)
    assert chore_state(row(completed_at=at(9, 59, 59)), c, now) == "early"
    assert chore_state(row(completed_at=at(10)), c, now) == "missed"
    # aware datetime in another zone compares correctly: 15:59:59 UTC == 09:59:59 MX
    utc = datetime(2026, 11, 2, 15, 59, 59, tzinfo=timezone.utc)
    assert chore_state(row(completed_at=utc), c, now) == "early"


def test_chore_state_variants():
    c = cfg()
    now = at(12)
    e = at(9)
    assert chore_state(row(approval=AP.APPROVED, completed_at=e), c, now) == "early"
    assert chore_state(row(grade="full", approval=AP.APPROVED, completed_at=e), c, now) == "early"
    assert chore_state(row(grade="partial", completed_at=e), c, now) == "missed"
    assert chore_state(row(grade="missed", completed_at=e), c, now) == "missed"
    assert chore_state(row(approval=AP.REJECTED, completed_at=e), c, now) == "missed"
    assert chore_state(row(completed_at=None), c, now) == "missed"
    assert chore_state(row(status=AS.TAKEN), c, now) == "missed"
    p = row(approval=AP.PENDING, completed_at=e)
    assert chore_state(p, c, now) == "pending"
    assert chore_state(p, c, now, grace=True) == "early"
    assert chore_state(row(approval=AP.PENDING, completed_at=at(10, 5)), c, now, grace=True) == "missed"


def test_chore_state_open():
    c = cfg()
    for st in (AS.PENDING, AS.OVERDUE, AS.CLAIMED):
        assert chore_state(row(status=st), c, at(9)) == "open"
        assert chore_state(row(status=st), c, at(10)) == "missed"
    assert chore_state(row(status=AS.PENDING), c, at(9, 59, 59)) == "open"


def test_day_result():
    assert day_result([]) == "neutral"
    assert day_result(["early", "missed", "open"]) == "missed"
    assert day_result(["early", "open", "pending"]) == "open"
    assert day_result(["early", "pending"]) == "pending"
    assert day_result(["early", "early"]) == "early"


def test_week_result():
    assert week_result(["early"], eligible=False, week_over=True) == "ineligible"
    assert week_result(["early", "missed"], eligible=True, week_over=False) == "missed"
    assert week_result(["early"], eligible=True, week_over=False) == "in_progress"
    assert week_result(["early", "pending"], eligible=True, week_over=True) == "pending"
    assert week_result(["early", "open"], eligible=True, week_over=True) == "pending"
    assert week_result(["early", "neutral"], eligible=True, week_over=True) == "early"
    assert week_result(["neutral"], eligible=True, week_over=True) == "neutral"
    assert week_result([], eligible=True, week_over=True) == "neutral"


def test_next_run_and_streak():
    assert next_run(2, "early") == 3
    assert next_run(2, "missed") == 0
    assert next_run(2, "neutral") == 2
    assert pays_streak("early", 3) and pays_streak("early", 6)
    assert not pays_streak("early", 4)
    assert not pays_streak("early", 0)
    assert not pays_streak("neutral", 3)


def test_early_bonus_points():
    assert early_bonus_points(10, 20) == 2
    assert early_bonus_points(3, 20) == 1
    assert early_bonus_points(10, 0) == 0
    assert early_bonus_points(0, 20) == 0
    assert early_bonus_points(-5, 20) == 0
    assert early_bonus_points(15, 10) == 2   # 1.5 half-up


def test_reminder_stage():
    t = day_times(cfg(), MON)
    assert reminder_stage(t.r1 - timedelta(seconds=1), t) is None
    assert reminder_stage(t.r1, t) == "r1"
    assert reminder_stage(t.r2 - timedelta(seconds=1), t) == "r1"
    assert reminder_stage(t.r2, t) == "r2"
    assert reminder_stage(t.deadline - timedelta(seconds=1), t) == "r2"
    assert reminder_stage(t.deadline, t) == "grabs"
    assert reminder_stage(t.deadline + GRABS_PUSH_WINDOW - timedelta(seconds=1), t) == "grabs"
    assert reminder_stage(t.deadline + GRABS_PUSH_WINDOW, t) is None


def test_week_bonus():
    assert week_bonus(80000, 5, "early") == 4000
    assert week_bonus(80000, 5, "pending") == 0
    assert week_bonus(0, 5, "early") == 0
    assert week_bonus(80000, 0, "early") == 0


def test_off_on_toggle_keeps_weeks_that_ran_under_the_earlier_period():
    """Switching off and on again starts a new period; it must not make the
    weeks that ran fully under the earlier period ineligible."""
    earlier = (datetime(2026, 10, 1, tzinfo=MX), at(12, day=MON + timedelta(days=8)))
    c = cfg(enabled_at=at(9, day=MON + timedelta(days=14)), past_periods=(earlier,))
    assert week_eligible(c, MON)                                # fully in the earlier period
    assert not week_eligible(c, MON + timedelta(days=7))        # off/on during that week
    assert week_eligible(c, MON + timedelta(days=14))           # current period
    assert is_active_day(c, MON)
    assert is_active_day(c, MON + timedelta(days=7))            # Mon R1 10:00 < off Tue 12:00
    assert not is_active_day(c, MON + timedelta(days=9))        # Wed: switched off
    assert is_active_day(c, MON + timedelta(days=14))


def test_past_periods_do_not_apply_while_switched_off():
    earlier = (datetime(2026, 10, 1, tzinfo=MX), at(12, day=MON + timedelta(days=8)))
    c = cfg(enabled=False, enabled_at=None, past_periods=(earlier,))
    assert not week_eligible(c, MON)
    assert not is_active_day(c, MON)


def test_from_family_reads_past_periods():
    fam = SimpleNamespace(early_bird_enabled=True, early_bird_enabled_at=None,
                          early_bird_deadline=time(11), early_bird_days=None,
                          early_bird_bonus_pct=20, early_bird_week_pct=5,
                          early_bird_streak_cents=100, timezone="America/Mexico_City",
                          chore_cutoff=time(20, 30), grab_window_end=time(22, 30),
                          early_bird_past_periods=[["2026-10-01T00:00:00+00:00",
                                                    "2026-10-20T12:00:00+00:00"]])
    c = EarlyBirdConfig.from_family(fam)
    assert c.past_periods == ((datetime(2026, 10, 1, tzinfo=timezone.utc),
                               datetime(2026, 10, 20, 12, tzinfo=timezone.utc)),)


def test_past_periods_outlive_the_paycheck_window():
    """A closed period must be kept while a week in it can still be paid."""
    from app.services.bank_service import PAYCHECK_LOOKBACK_WEEKS
    from app.services.early_bird_rules import PAST_PERIOD_KEEP

    assert PAST_PERIOD_KEEP > timedelta(weeks=PAYCHECK_LOOKBACK_WEEKS)
