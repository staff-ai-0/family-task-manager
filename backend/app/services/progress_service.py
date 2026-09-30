"""UX-D1 progression: a daily chore streak and a 10-step rank, derived from
history (never stored counters) — see docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md.

This module holds the pure rules; the DB queries live in ProgressService below
them so the rules stay testable without a database.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

# Cumulative XP needed to REACH rank i+1 (index 0 = rank 1).
RANK_THRESHOLDS: tuple[int, ...] = (0, 100, 300, 600, 1000, 1600, 2500, 3800, 5500, 8000)
MAX_RANK = len(RANK_THRESHOLDS)
STREAK_LOOKBACK_DAYS = 365


def rank_for_xp(xp: int) -> int:
    """Highest rank whose threshold is met (1..MAX_RANK)."""
    rank = 1
    for i, threshold in enumerate(RANK_THRESHOLDS):
        if xp >= threshold:
            rank = i + 1
    return rank


def rank_floor(rank: int) -> int:
    return RANK_THRESHOLDS[max(1, min(rank, MAX_RANK)) - 1]


def next_rank_xp(rank: int) -> int | None:
    return RANK_THRESHOLDS[rank] if rank < MAX_RANK else None


class DayState(str, Enum):
    none = "none"      # nothing due — skipped
    done = "done"      # every due chore done by the end of the day
    missed = "missed"  # a due chore not done (or graded missed / rejected)
    shield = "shield"  # a missed day forgiven by the weekly pass
    today = "today"    # today, not complete yet
    future = "future"  # after today


@dataclass
class StreakResult:
    days: int
    week: list[tuple[date, DayState]]
    shield_used: bool


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_streak(states: dict[date, DayState], today: date) -> StreakResult:
    """Walk forward from the lookback start to today (chronological, so the
    FIRST miss of each Monday–Sunday week is the forgiven one).

    done → +1 · none/today → no change · missed → shield if the week's pass is
    unused, else reset to 0. Today only counts once it is done.
    """
    start = today - timedelta(days=STREAK_LOOKBACK_DAYS)
    days = 0
    shield_weeks: set[date] = set()
    resolved: dict[date, DayState] = {}
    cur = start
    while cur <= today:
        state = states.get(cur, DayState.none)
        if cur == today and state != DayState.done:
            state = DayState.today
        if state == DayState.done:
            days += 1
        elif state == DayState.missed:
            week = _monday(cur)
            if week not in shield_weeks:
                shield_weeks.add(week)
                state = DayState.shield
            else:
                days = 0
        resolved[cur] = state
        cur += timedelta(days=1)
    # The walk covers at most STREAK_LOOKBACK_DAYS + 1 days (incl. today).
    days = min(days, STREAK_LOOKBACK_DAYS)

    monday = _monday(today)
    week = []
    for i in range(7):
        day = monday + timedelta(days=i)
        week.append((day, resolved.get(day, DayState.future if day > today else DayState.none)))
    return StreakResult(days=days, week=week, shield_used=monday in shield_weeks)
