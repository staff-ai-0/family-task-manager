"""UX-D3 weekly quest: one personal goal per kid per week, with a points bonus
paid once when it is reached — see
docs/superpowers/specs/2026-10-01-ux-d3-weekly-quest-design.md.

Progress is derived on read (like UX-D1/D2); only the week's quest row is
stored (`weekly_quests`: type, target, bonus, paid/seen marks). This module
holds the pure rules; the DB queries live in QuestService below them.
Copy (titles, emoji) lives only in frontend/src/lib/quest.ts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus, AssignmentStatus

# Rotation order -> default goal (also the goal for a kid with no history).
QUESTS: dict[str, int] = {"on_time": 3, "extra_mile": 1, "perfect_days": 2, "go_getter": 1}
# Open-ended work has no "chores left this week" ceiling; cap the goal instead.
OPEN_ENDED = ("extra_mile", "go_getter")
OPEN_ENDED_CAP = 7
HISTORY_WEEKS = 4
# Work awaiting a parent's review does not count until approved: the bonus is
# real points and is never taken back.
_COUNTING = (ApprovalStatus.NONE, ApprovalStatus.APPROVED)


def week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def rotation(week_start: date, user_id: UUID) -> list[str]:
    """The four quest keys, starting at this kid's slot for this week. Each
    kid moves one step per week; siblings start at different slots."""
    keys = list(QUESTS)
    start = (week_start.toordinal() // 7 + user_id.int) % len(keys)
    return keys[start:] + keys[:start]


def size_target(default: int, history_total: int, done: int, possible: Optional[int]) -> Optional[int]:
    """Goal for one quest type, or None when it cannot be this week's quest.

    history_total — the kid's count for this type over the previous
    HISTORY_WEEKS full weeks; done — already achieved this week; possible —
    how many more can still be achieved this week (None = type not offered).
    """
    if possible is None:
        return None
    # ceil(1.1 x average) in integers: ceil(11 * total / (10 * weeks)).
    stretch = max(default, -(-history_total * 11 // (10 * HISTORY_WEEKS)))
    target = min(stretch, done + possible)
    # A quest never starts finished, and never asks for the impossible.
    return target if target >= done + 1 else None


@dataclass(frozen=True)
class ChoreRow:
    assigned_date: date
    status: AssignmentStatus
    completed_at: Optional[datetime]
    grade: Optional[str]
    approval: ApprovalStatus
    is_bonus: bool


def _on_time(row: ChoreRow, tz: ZoneInfo) -> bool:
    # Legacy rows completed before timestamps existed count as on time (D1's rule).
    return row.completed_at is None or row.completed_at.astimezone(tz).date() <= row.assigned_date


def chore_state(row: ChoreRow, today: date, tz: ZoneInfo) -> str:
    """'yes' — counts on time now · 'maybe' — can still count · 'no' — cannot."""
    if row.status == AssignmentStatus.COMPLETED:
        if row.grade == "missed" or row.approval == ApprovalStatus.REJECTED or not _on_time(row, tz):
            return "no"
        return "yes" if row.approval in _COUNTING else "maybe"
    if row.status == AssignmentStatus.PENDING and row.assigned_date >= today:
        return "maybe"
    return "no"


@dataclass(frozen=True)
class WeekStats:
    done: dict[str, int]       # per quest key: achieved in the period
    possible: dict[str, int]   # chore types: how many more can still count


def week_stats(rows: list[ChoreRow], gigs_approved: int, today: date, tz: ZoneInfo) -> WeekStats:
    """Counts for every quest type over the given rows (one week, or several
    for history). `possible` is only meaningful for the chore types."""
    due = [r for r in rows if not r.is_bonus and r.status != AssignmentStatus.CANCELLED]
    states = [(r.assigned_date, chore_state(r, today, tz)) for r in due]
    by_day: dict[date, list[str]] = {}
    for day, state in states:
        by_day.setdefault(day, []).append(state)
    bonus_done = sum(
        1 for r in rows
        if r.is_bonus and r.status == AssignmentStatus.COMPLETED and r.grade != "missed" and r.approval in _COUNTING
    )
    return WeekStats(
        done={
            "on_time": sum(1 for _, s in states if s == "yes"),
            "perfect_days": sum(1 for ss in by_day.values() if all(s == "yes" for s in ss)),
            "extra_mile": bonus_done,
            "go_getter": int(gigs_approved),
        },
        possible={
            "on_time": sum(1 for _, s in states if s == "maybe"),
            "perfect_days": sum(1 for ss in by_day.values() if "no" not in ss and "maybe" in ss),
            "extra_mile": 0,
            "go_getter": 0,
        },
    )


def pick_quest(
    order: list[str], stats: WeekStats, history: dict[str, int], offered: dict[str, bool],
) -> Optional[tuple[str, int]]:
    """First type in `order` that is offered and achievable, with its goal."""
    for key in order:
        if not offered.get(key, False):
            continue
        done = stats.done.get(key, 0)
        possible = max(0, OPEN_ENDED_CAP - done) if key in OPEN_ENDED else stats.possible.get(key, 0)
        target = size_target(QUESTS[key], history.get(key, 0), done, possible)
        if target is not None:
            return key, target
    return None
