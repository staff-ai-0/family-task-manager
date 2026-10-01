"""UX-D1 pure rules: rank curve + streak walk (no DB)."""
from datetime import date, timedelta

import pytest

from app.services.progress_service import (
    DayState as S,
    MAX_RANK,
    RANK_THRESHOLDS,
    compute_streak,
    next_rank_xp,
    rank_floor,
    rank_for_xp,
)

# A fixed Thursday so week maths is readable: week = Mon 2026-09-28 .. Sun 2026-10-04.
TODAY = date(2026, 10, 1)


def d(offset: int) -> date:
    return TODAY + timedelta(days=offset)


class TestRankCurve:
    def test_thresholds_are_the_spec_values(self):
        assert RANK_THRESHOLDS == (0, 100, 300, 600, 1000, 1600, 2500, 3800, 5500, 8000)
        assert MAX_RANK == 10

    @pytest.mark.parametrize("xp,rank", [(0, 1), (99, 1), (100, 2), (299, 2), (300, 3), (7999, 9), (8000, 10), (10**9, 10)])
    def test_rank_for_xp(self, xp, rank):
        assert rank_for_xp(xp) == rank

    def test_negative_xp_is_rank_one(self):
        assert rank_for_xp(-5) == 1

    def test_floor_and_next(self):
        assert rank_floor(1) == 0 and next_rank_xp(1) == 100
        assert rank_floor(4) == 600 and next_rank_xp(4) == 1000
        assert rank_floor(10) == 8000 and next_rank_xp(10) is None


class TestStreak:
    def test_all_done_counts_every_day_through_yesterday(self):
        states = {d(-i): S.done for i in range(1, 6)}
        assert compute_streak(states, TODAY).days == 5

    def test_today_counts_only_once_done(self):
        states = {d(-1): S.done, d(-2): S.done, TODAY: S.today}
        assert compute_streak(states, TODAY).days == 2
        states[TODAY] = S.done
        assert compute_streak(states, TODAY).days == 3

    def test_none_days_are_skipped(self):
        states = {d(-1): S.done, d(-2): S.none, d(-3): S.done}
        assert compute_streak(states, TODAY).days == 2

    def test_first_miss_of_the_week_is_forgiven(self):
        # Mon done, Tue missed (forgiven), Wed done -> 2
        states = {d(-3): S.done, d(-2): S.missed, d(-1): S.done}
        r = compute_streak(states, TODAY)
        assert r.days == 2
        assert r.shield_used is True
        assert dict(r.week)[d(-2)] == S.shield

    def test_second_miss_in_the_same_week_resets(self):
        # Mon missed (shield), Tue done, Wed missed (reset) -> 0 through yesterday
        states = {d(-3): S.missed, d(-2): S.done, d(-1): S.missed}
        r = compute_streak(states, TODAY)
        assert r.days == 0
        assert dict(r.week)[d(-3)] == S.shield
        assert dict(r.week)[d(-1)] == S.missed

    def test_misses_in_different_weeks_are_each_forgiven(self):
        # last week's Friday missed, this week's Tuesday missed, rest done
        states = {d(-i): S.done for i in range(1, 12)}
        states[d(-6)] = S.missed   # Fri 2026-09-25 (previous week)
        states[d(-2)] = S.missed   # Tue 2026-09-29 (this week)
        assert compute_streak(states, TODAY).days == 9

    def test_lookback_is_365_days(self):
        states = {d(-i): S.done for i in range(1, 500)}
        assert compute_streak(states, TODAY).days == 365

    def test_week_strip_is_monday_to_sunday_with_future_days(self):
        r = compute_streak({d(-1): S.done}, TODAY)
        days = [day for day, _ in r.week]
        assert days[0] == date(2026, 9, 28) and days[-1] == date(2026, 10, 4) and len(days) == 7
        w = dict(r.week)
        assert w[d(-1)] == S.done and w[d(-3)] == S.none and w[TODAY] == S.today and w[d(1)] == S.future


class TestBestAndPerfectWeeks:
    """UX-D2: two extra outputs of the same walk."""

    def test_best_is_the_peak_and_survives_a_reset(self):
        # 10 done days (Fri 09-11 .. Sun 09-20), Mon 09-21 missed (shield),
        # Tue 09-22 missed (reset), then two done days.
        states = {d(-i): S.done for i in range(11, 21)}
        states[d(-10)] = S.missed
        states[d(-9)] = S.missed
        states[d(-2)] = S.done
        states[d(-1)] = S.done
        r = compute_streak(states, TODAY)
        assert r.days == 2
        assert r.best == 10

    def test_best_equals_days_when_never_reset(self):
        r = compute_streak({d(-i): S.done for i in range(1, 6)}, TODAY)
        assert r.days == 5 and r.best == 5

    def test_best_is_capped_at_the_lookback(self):
        assert compute_streak({d(-i): S.done for i in range(1, 500)}, TODAY).best == 365

    def test_three_full_weeks_done_are_three_perfect_weeks(self):
        # Mon 2026-09-07 .. Sun 2026-09-27, plus this week's Mon-Wed.
        states = {d(-i): S.done for i in range(1, 25)}
        assert compute_streak(states, TODAY).perfect_weeks == 3

    def test_a_week_with_a_forgiven_miss_is_not_perfect(self):
        # Week of Mon 09-21: all done except Wed 09-23 (missed -> shield).
        states = {d(-i): S.done for i in range(4, 11)}
        states[d(-8)] = S.missed
        assert compute_streak(states, TODAY).perfect_weeks == 0

    def test_a_week_with_nothing_due_is_not_perfect(self):
        assert compute_streak({}, TODAY).perfect_weeks == 0

    def test_one_done_day_and_the_rest_free_is_perfect(self):
        assert compute_streak({d(-7): S.done}, TODAY).perfect_weeks == 1   # Thu 09-24

    def test_the_current_week_never_counts(self):
        states = {d(-3): S.done, d(-2): S.done, d(-1): S.done, TODAY: S.done}
        assert compute_streak(states, TODAY).perfect_weeks == 0

    def test_a_week_cut_by_the_lookback_start_is_not_perfect(self):
        # The walk starts Wed 2025-10-01; that week's Monday (09-29) is outside it.
        states = {d(-i): S.done for i in range(361, 366)}      # Wed 10-01 .. Sun 10-05
        assert compute_streak(states, TODAY).perfect_weeks == 0
        states[d(-360)] = S.done                               # Mon 2025-10-06
        assert compute_streak(states, TODAY).perfect_weeks == 1
