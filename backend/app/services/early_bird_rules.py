"""Early Bird pure rules (no DB): deadline instants, per-chore / day / week
results, streak and bonus arithmetic. See the 2026-11-07 early-bird spec."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus, AssignmentStatus
from app.services.bank_service import _safe_zoneinfo

STREAK_WEEKS = 3
R1_BEFORE = timedelta(minutes=60)
R2_BEFORE = timedelta(minutes=30)
GRABS_PUSH_WINDOW = timedelta(minutes=60)
SETTLE_LOOKBACK_WEEKS = 3
PENDING_GRACE_DAYS = 7
# Settlement stops at the first week still "pending" and resumes next sweep.
# That is only safe if the lookback window outlasts the grace period (the week
# that stops the walk must still be inside the window when grace expires);
# otherwise an unresolved week would age out of the window and never settle.
assert SETTLE_LOOKBACK_WEEKS * 7 > PENDING_GRACE_DAYS + 7, (
    "SETTLE_LOOKBACK_WEEKS must cover PENDING_GRACE_DAYS plus one week"
)


@dataclass(frozen=True)
class EarlyBirdConfig:
    enabled: bool
    enabled_at: Optional[datetime]
    deadline: time
    days: Optional[frozenset[int]]  # weekdays Mon=0; None = every day
    bonus_pct: int
    week_pct: int
    streak_cents: int
    tz: ZoneInfo

    @classmethod
    def from_family(cls, fam) -> "EarlyBirdConfig":
        days = fam.early_bird_days
        return cls(
            enabled=bool(fam.early_bird_enabled),
            enabled_at=fam.early_bird_enabled_at,
            deadline=fam.early_bird_deadline,
            days=None if days is None else frozenset(days),
            bonus_pct=fam.early_bird_bonus_pct,
            week_pct=fam.early_bird_week_pct,
            streak_cents=fam.early_bird_streak_cents,
            tz=_safe_zoneinfo(fam.timezone),
        )


@dataclass(frozen=True)
class DayTimes:
    r1: datetime
    r2: datetime
    deadline: datetime


def day_times(cfg: EarlyBirdConfig, day: date) -> DayTimes:
    deadline = datetime.combine(day, cfg.deadline, tzinfo=cfg.tz)
    return DayTimes(r1=deadline - R1_BEFORE, r2=deadline - R2_BEFORE, deadline=deadline)


def is_active_day(cfg: EarlyBirdConfig, day: date) -> bool:
    if not cfg.enabled or cfg.enabled_at is None:
        return False
    if cfg.days is not None and day.weekday() not in cfg.days:
        return False
    return day_times(cfg, day).r1 > cfg.enabled_at


def week_eligible(cfg: EarlyBirdConfig, monday: date) -> bool:
    if not cfg.enabled or cfg.enabled_at is None:
        return False
    return cfg.enabled_at < day_times(cfg, monday).r1


@dataclass(frozen=True)
class CoveredRow:
    assignment_id: UUID
    assigned_date: date
    status: AssignmentStatus
    approval: ApprovalStatus
    grade: Optional[str]
    completed_at: Optional[datetime]


ChoreState = Literal["early", "pending", "open", "missed"]


def chore_state(row: CoveredRow, cfg: EarlyBirdConfig, now: datetime, *, grace: bool = False) -> ChoreState:
    r1 = day_times(cfg, row.assigned_date).r1
    if row.status == AssignmentStatus.COMPLETED:
        if row.completed_at is None or row.completed_at >= r1:
            return "missed"
        if row.grade in ("missed", "partial"):
            return "missed"
        if row.approval in (ApprovalStatus.NONE, ApprovalStatus.APPROVED):
            return "early"
        if row.approval == ApprovalStatus.PENDING:
            return "early" if grace else "pending"
        return "missed"
    if row.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE, AssignmentStatus.CLAIMED):
        return "open" if now < r1 else "missed"
    return "missed"


def day_result(states: list[str]) -> Literal["early", "missed", "pending", "open", "neutral"]:
    if not states:
        return "neutral"
    if "missed" in states:
        return "missed"
    if "open" in states:
        return "open"
    if "pending" in states:
        return "pending"
    return "early"


def week_result(
    day_results: list[str], *, eligible: bool, week_over: bool
) -> Literal["ineligible", "early", "missed", "neutral", "pending", "in_progress"]:
    if not eligible:
        return "ineligible"
    if "missed" in day_results:
        return "missed"
    if not week_over:
        return "in_progress"
    if "pending" in day_results or "open" in day_results:
        return "pending"
    if "early" in day_results:
        return "early"
    return "neutral"


def next_run(prev_run: int, result: str) -> int:
    if result == "early":
        return prev_run + 1
    if result == "missed":
        return 0
    return prev_run


def pays_streak(result: str, run: int) -> bool:
    return result == "early" and run > 0 and run % STREAK_WEEKS == 0


def early_bonus_points(effective_points: int, pct: int) -> int:
    if effective_points <= 0 or pct <= 0:
        return 0
    return max(1, (effective_points * pct + 50) // 100)


def reminder_stage(now: datetime, t: DayTimes) -> Optional[Literal["r1", "r2", "grabs"]]:
    if t.r1 <= now < t.r2:
        return "r1"
    if t.r2 <= now < t.deadline:
        return "r2"
    if t.deadline <= now < t.deadline + GRABS_PUSH_WINDOW:
        return "grabs"
    return None


def week_bonus(base_cents: int, pct: int, result: str) -> int:
    if result == "early" and base_cents > 0 and pct > 0:
        return base_cents * pct // 100
    return 0
