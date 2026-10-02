"""UX-D4a pings: the app-icon number and the evening smart reminders for kids.

Pure rules first (no DB), then the family-scoped queries. A smart reminder's
only send record is the notification row it creates — see run_evening_sweep.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.models.notification import NotificationType as NT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus
from app.services.quest_service import ChoreRow, bonus_state, chore_state

# The sweep acts while the family's local hour is 18, 19 or 20. With the server
# up, the 18:00 run handles everyone; the later hours only recover a run that
# was missed. Nothing is sent after 20:59.
PING_FIRST_HOUR = 18
PING_LAST_HOUR = 20
STREAK_PING_MIN_DAYS = 3
PING_TAG = "ftm-smart"
PING_TYPES = (NT.STREAK_AT_RISK, NT.QUEST_NUDGE)
_OPEN = (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)


def in_ping_window(local_now: datetime) -> bool:
    return PING_FIRST_HOUR <= local_now.hour <= PING_LAST_HOUR


def today_facts(rows: list[ChoreRow]) -> tuple[int, bool]:
    """(open_today, day_lost) from the kid's assignments dated today.

    open_today — mandatory chores the kid can still finish. day_lost — a
    mandatory chore today is already graded missed or rejected, so finishing
    the rest cannot save the day (and a "finish it to keep it" push would lie).
    """
    chores = [r for r in rows if not r.is_bonus and r.status != AssignmentStatus.CANCELLED]
    open_today = sum(1 for r in chores if r.status in _OPEN)
    day_lost = any(r.grade == "missed" or r.approval == ApprovalStatus.REJECTED for r in chores)
    return open_today, day_lost


def streak_ping(days: int, shield_used: bool, open_today: int, day_lost: bool) -> Optional[str]:
    """Copy key for the streak-at-risk reminder, or None when it must not be sent."""
    if days < STREAK_PING_MIN_DAYS or open_today < 1 or day_lost:
        return None
    key = "streak_at_risk_last" if shield_used else "streak_at_risk_pass"
    return f"{key}_one" if open_today == 1 else key


def quest_can_do_today(quest: str, rows: list[ChoreRow], today: date, tz: ZoneInfo, gigs_open: int) -> bool:
    """Can the kid still take the quest's missing step today? `rows` are the
    kid's assignments dated today; the states are the quest's own rules."""
    live = [r for r in rows if r.status != AssignmentStatus.CANCELLED]
    chores = [r for r in live if not r.is_bonus]
    doable = any(r.status == AssignmentStatus.PENDING and chore_state(r, today, tz) == "maybe" for r in chores)
    if quest == "on_time":
        return doable
    if quest == "perfect_days":
        return doable and all(chore_state(r, today, tz) != "no" for r in chores)
    if quest == "extra_mile":
        return any(
            r.is_bonus and r.status != AssignmentStatus.COMPLETED and bonus_state(r, today) == "maybe"
            for r in live
        )
    if quest == "go_getter":
        return gigs_open > 0
    return False


def quest_ping(progress: int, target: int, rewarded: bool, can_do_today: bool, nudged_this_week: bool) -> bool:
    return not rewarded and not nudged_this_week and can_do_today and progress == target - 1


def pick_ping(streak_key: Optional[str], quest_ok: bool) -> Optional[str]:
    """At most one reminder a day: the streak one wins, the quest nudge waits."""
    if streak_key:
        return streak_key
    return "quest_nudge" if quest_ok else None
