"""Early Bird pure rules (no DB): deadline instants, per-chore / day / week
results, streak and bonus arithmetic. See the 2026-11-07 early-bird spec."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus, AssignmentStatus
from app.core.time_utils import safe_zoneinfo

STREAK_WEEKS = 3
# R1/R2 are reminder offsets only (first / second teen push); the early
# cutoff everywhere is the deadline itself.
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
    cutoff: time  # chores must be done before this to count as completed
    grab_end: time  # end of the up-for-grabs window
    # Earlier on-periods, closed by a switch-off: ((start, end), ...). The
    # current period is (enabled_at, open). Kept so an off->on toggle does not
    # retroactively make the weeks that already ran under the feature ineligible.
    past_periods: tuple[tuple[datetime, datetime], ...] = ()

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
            tz=safe_zoneinfo(fam.timezone),
            cutoff=fam.chore_cutoff,
            grab_end=fam.grab_window_end,
            past_periods=tuple(
                (datetime.fromisoformat(start), datetime.fromisoformat(end))
                for start, end in (getattr(fam, "early_bird_past_periods", None) or ())
            ),
        )


@dataclass(frozen=True)
class DayTimes:
    r1: datetime
    r2: datetime
    deadline: datetime
    cutoff: datetime
    grab_end: datetime


def day_times(cfg: EarlyBirdConfig, day: date) -> DayTimes:
    deadline = datetime.combine(day, cfg.deadline, tzinfo=cfg.tz)
    return DayTimes(
        r1=deadline - R1_BEFORE,
        r2=deadline - R2_BEFORE,
        deadline=deadline,
        cutoff=datetime.combine(day, cfg.cutoff, tzinfo=cfg.tz),
        grab_end=datetime.combine(day, cfg.grab_end, tzinfo=cfg.tz),
    )


def _on_periods(cfg: EarlyBirdConfig) -> list[tuple[datetime, Optional[datetime]]]:
    """Every (start, end) the feature was on; end None = still on. Empty while
    switched off: an off feature computes nothing, earlier periods included."""
    if not cfg.enabled or cfg.enabled_at is None:
        return []
    return [*cfg.past_periods, (cfg.enabled_at, None)]


def _on_throughout(cfg: EarlyBirdConfig, start: datetime, end: datetime) -> bool:
    """One on-period spans (start, end]: switched on before ``start`` and not
    switched off before ``end``."""
    return any(
        on < start and (off is None or off > end) for on, off in _on_periods(cfg)
    )


# A closed period is kept while a week inside it can still be paid or settled:
# bank_service.PAYCHECK_LOOKBACK_WEEKS (8) plus a margin — pinned by a test so
# this pure module does not import the bank service.
PAST_PERIOD_KEEP = timedelta(weeks=10)
assert PAST_PERIOD_KEEP > timedelta(weeks=SETTLE_LOOKBACK_WEEKS + 1)


def close_period(past: Optional[list], start: datetime, end: datetime) -> list:
    """``families.early_bird_past_periods`` after a switch-off that ends the
    period begun at ``start``: appended, and pruned past PAST_PERIOD_KEEP."""
    kept = [p for p in (past or []) if datetime.fromisoformat(p[1]) > end - PAST_PERIOD_KEEP]
    return [*kept, [start.isoformat(), end.isoformat()]]


def is_active_day(cfg: EarlyBirdConfig, day: date) -> bool:
    if cfg.days is not None and day.weekday() not in cfg.days:
        return False
    deadline = day_times(cfg, day).deadline
    return _on_throughout(cfg, deadline, deadline)


def week_eligible(cfg: EarlyBirdConfig, monday: date) -> bool:
    """On from before Monday's deadline through Sunday's deadline (when the week is over)
    without a switch-off: the week you switch it on never counts."""
    return _on_throughout(
        cfg, day_times(cfg, monday).deadline, day_times(cfg, monday + timedelta(days=6)).deadline
    )


@dataclass(frozen=True)
class CoveredRow:
    assignment_id: UUID
    assigned_date: date
    status: AssignmentStatus
    approval: ApprovalStatus
    grade: Optional[str]
    completed_at: Optional[datetime]
    # Set by the parent's retroactive "mark done" (explicit action): counts as
    # completed whatever completed_at says.
    parent_marked: bool = False


ChoreState = Literal["early", "pending", "open", "missed"]


def chore_state(row: CoveredRow, cfg: EarlyBirdConfig, now: datetime, *, grace: bool = False) -> ChoreState:
    deadline = day_times(cfg, row.assigned_date).deadline
    if row.status == AssignmentStatus.COMPLETED:
        if row.completed_at is None or row.completed_at >= deadline:
            return "missed"
        if row.grade in ("missed", "partial"):
            return "missed"
        if row.approval in (ApprovalStatus.NONE, ApprovalStatus.APPROVED):
            return "early"
        if row.approval == ApprovalStatus.PENDING:
            return "early" if grace else "pending"
        return "missed"
    if row.status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE, AssignmentStatus.CLAIMED):
        return "open" if now < deadline else "missed"
    return "missed"


def completed_in_time(row: CoveredRow, cfg: EarlyBirdConfig, *, grace: bool = False) -> bool:
    """Counts as completed for the weekly ladder: done before the day's cutoff
    (a parent-marked row is exempt from the time test), not graded
    missed/partial, and approved (or pending review when ``grace``)."""
    if row.status != AssignmentStatus.COMPLETED or row.completed_at is None:
        return False
    if not row.parent_marked and row.completed_at >= day_times(cfg, row.assigned_date).cutoff:
        return False
    if row.grade in ("missed", "partial"):
        return False
    if row.approval in (ApprovalStatus.NONE, ApprovalStatus.APPROVED):
        return True
    return row.approval == ApprovalStatus.PENDING and grace


def done_early(row: CoveredRow, cfg: EarlyBirdConfig, *, grace: bool = False) -> bool:
    """Completed in time AND before the deadline (11:00, not R1)."""
    return (
        not row.parent_marked
        and completed_in_time(row, cfg, grace=grace)
        and row.completed_at < day_times(cfg, row.assigned_date).deadline
    )


@dataclass(frozen=True)
class LadderResult:
    tier: Literal["neutral", "no_pay", "per_task", "bonus"]
    bonus_pct: int
    completed: int
    early: int
    total: int
    # True once the week can no longer change (Sunday's cutoff has passed);
    # filled by the service, never by week_ladder.
    final: bool = False

    # Floored on purpose: a rounded 59.5 % would read "60 %" on a week the
    # ladder (cross-multiplied, exact) puts in no_pay.
    @property
    def completed_pct(self) -> int:
        return self.completed * 100 // self.total if self.total > 0 else 0

    @property
    def early_pct(self) -> int:
        return self.early * 100 // self.total if self.total > 0 else 0


def week_ladder(completed: int, early: int, total: int) -> LadderResult:
    """Weekly pay tier from counts. Integer cross-multiplication only; every
    boundary is inclusive."""
    def result(tier, pct=0):
        return LadderResult(tier, pct, completed, early, total)

    if total <= 0:
        return result("neutral")
    if completed * 100 < 60 * total:
        return result("no_pay")
    if completed != total:
        return result("per_task")
    if early * 100 >= 100 * total:
        return result("bonus", 15)
    if early * 100 >= 90 * total:
        return result("bonus", 10)
    if early * 100 >= 80 * total:
        return result("bonus", 5)
    return result("bonus", 0)


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


def role_may_take(allowed_roles, role_value: str) -> bool:
    """A template's ``allowed_roles`` (empty/None = everyone) admits the role."""
    return not allowed_roles or role_value in allowed_roles


def early_bonus_points(effective_points: int, pct: int) -> int:
    if effective_points <= 0 or pct <= 0:
        return 0
    return max(1, (effective_points * pct + 50) // 100)


def reminder_stage(now: datetime, t: DayTimes) -> Optional[Literal["r1", "r2", "grabs"]]:
    if t.r1 <= now < t.r2:
        return "r1"
    if t.r2 <= now < t.deadline:
        return "r2"
    if t.cutoff <= now < min(t.grab_end, t.cutoff + GRABS_PUSH_WINDOW):
        return "grabs"
    return None


def grab_window_open(now: datetime, t: DayTimes) -> bool:
    """The up-for-grabs window: cutoff <= now < grab_end (family-local day)."""
    return t.cutoff <= now < t.grab_end


def chore_expired(now: datetime, t: DayTimes) -> bool:
    """True once the day's cutoff has passed: the owner can no longer complete."""
    return now >= t.cutoff
