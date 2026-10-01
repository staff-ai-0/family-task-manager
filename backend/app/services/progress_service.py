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
    # UX-D2 badges read these two; D1 surfaces ignore them.
    best: int = 0           # peak of the running counter anywhere in the walk
    perfect_weeks: int = 0  # finished Mon–Sun weeks inside the walk: ≥1 done day, no missed/shield


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_streak(states: dict[date, DayState], today: date) -> StreakResult:
    """Walk forward from the lookback start to today (chronological, so the
    FIRST miss of each Monday–Sunday week is the forgiven one).

    done → +1 · none/today → no change · missed → shield if the week's pass is
    unused, else reset to 0. Today only counts once it is done.

    Also reports `best` (the counter's peak) and `perfect_weeks` for UX-D2 badges.
    """
    start = today - timedelta(days=STREAK_LOOKBACK_DAYS)
    days = 0
    best = 0
    shield_weeks: set[date] = set()
    resolved: dict[date, DayState] = {}
    cur = start
    while cur <= today:
        state = states.get(cur, DayState.none)
        if cur == today and state != DayState.done:
            state = DayState.today
        if state == DayState.done:
            days += 1
            best = max(best, days)
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
    best = min(best, STREAK_LOOKBACK_DAYS)

    # Perfect weeks: only weeks that ended before today's week and whose
    # Monday is inside the walk (a week cut by the lookback start is skipped).
    perfect_weeks = 0
    week_start = _monday(start)
    if week_start < start:
        week_start += timedelta(days=7)
    this_monday = _monday(today)
    while week_start < this_monday:
        days_of_week = [resolved.get(week_start + timedelta(days=i), DayState.none) for i in range(7)]
        if (
            DayState.done in days_of_week
            and DayState.missed not in days_of_week
            and DayState.shield not in days_of_week
        ):
            perfect_weeks += 1
        week_start += timedelta(days=7)

    monday = _monday(today)
    week = []
    for i in range(7):
        day = monday + timedelta(days=i)
        week.append((day, resolved.get(day, DayState.future if day > today else DayState.none)))
    return StreakResult(
        days=days, week=week, shield_used=monday in shield_weeks,
        best=best, perfect_weeks=perfect_weeks,
    )


# ── Queries (family-scoped) ──────────────────────────────────────────────
from datetime import datetime  # noqa: E402
from uuid import UUID  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from sqlalchemy import and_, func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.models.cash_transaction import CashTransaction, CashTransactionType  # noqa: E402
from app.models.family import Family  # noqa: E402
from app.models.point_transaction import PointTransaction, TransactionType  # noqa: E402
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment  # noqa: E402
from app.models.task_template import TaskTemplate  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.schemas.progress import DayEntry, ProgressResponse  # noqa: E402
from app.services.bank_service import _safe_zoneinfo  # noqa: E402

XP_POINT_TYPES = (TransactionType.TASK_COMPLETED, TransactionType.BONUS, TransactionType.GIG_APPROVED)
KID_ROLES = (UserRole.CHILD, UserRole.TEEN)


class ProgressService:
    @staticmethod
    async def family_today(db: AsyncSession, family_id: UUID) -> tuple[date, ZoneInfo]:
        tz = _safe_zoneinfo((await db.execute(select(Family.timezone).where(Family.id == family_id))).scalar())
        return datetime.now(tz).date(), tz

    @staticmethod
    async def xp_for(db: AsyncSession, family_id: UUID, user_id: UUID) -> int:
        """Sum ALL rows of the earning types — positive AND negative — then
        clamp each part at 0, instead of filtering to `> 0` rows.

        Parent corrections write negative rows against the same types as the
        original award (reopening a chore claws back TASK_COMPLETED; a
        collaboration gig re-split claws back GIG_APPROVED via
        `_settle_collaboration`), so filtering to `points > 0` /
        `amount_cents > 0` discarded the claw-back and let a redo
        double-count. Cash is netted in CENTS and floored AFTER summing —
        flooring each `gig_earned` row (one per jar from
        `CashService.credit_split_rows`) before summing undercounts a split
        gig (e.g. $5 split 350/100/50 cents floors to 3+1+0=4, not 5).
        """
        points = (await db.execute(
            select(func.coalesce(func.sum(PointTransaction.points), 0)).where(
                PointTransaction.family_id == family_id,
                PointTransaction.user_id == user_id,
                PointTransaction.type.in_(XP_POINT_TYPES),
            )
        )).scalar()
        pesos_cents = (await db.execute(
            select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                CashTransaction.family_id == family_id,
                CashTransaction.user_id == user_id,
                CashTransaction.type == CashTransactionType.GIG_EARNED,
            )
        )).scalar()
        points_xp = max(0, int(points or 0))
        cash_xp = max(0, int(pesos_cents or 0)) // 100
        return points_xp + cash_xp

    @staticmethod
    async def day_states(
        db: AsyncSession, family_id: UUID, user_id: UUID, today: date, tz: ZoneInfo,
    ) -> dict[date, DayState]:
        start = today - timedelta(days=STREAK_LOOKBACK_DAYS)
        rows = (await db.execute(
            select(
                TaskAssignment.assigned_date,
                TaskAssignment.status,
                TaskAssignment.completed_at,
                TaskAssignment.completion_grade,
                TaskAssignment.approval_status,
            )
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(and_(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskTemplate.is_bonus.is_(False),
                TaskAssignment.status != AssignmentStatus.CANCELLED,
                TaskAssignment.assigned_date >= start,
                TaskAssignment.assigned_date <= today,
            ))
        )).all()

        # Badge counts use a stricter variant of this rule — see BadgeService.counts_for.
        def done_in_time(row) -> bool:
            if row.completion_grade == "missed" or row.approval_status == ApprovalStatus.REJECTED:
                return False
            if row.status != AssignmentStatus.COMPLETED:
                return False
            if row.completed_at is None:  # legacy rows: completed, no timestamp → on time
                return True
            return row.completed_at.astimezone(tz).date() <= row.assigned_date

        by_day: dict[date, bool] = {}
        for row in rows:
            ok = done_in_time(row)
            by_day[row.assigned_date] = by_day.get(row.assigned_date, True) and ok

        states: dict[date, DayState] = {}
        for day, all_done in by_day.items():
            if all_done:
                states[day] = DayState.done
            else:
                states[day] = DayState.today if day == today else DayState.missed
        return states

    @staticmethod
    async def ack_rank(db: AsyncSession, user: User, rank: int) -> None:
        """Raise last_seen_rank up to min(rank, held) — never lowers it.

        A single atomic UPDATE, not a read-modify-write on the ORM object:
        two concurrent acks (e.g. two tabs) each holding a stale in-memory
        `user.last_seen_rank` must not be able to race each other into
        lowering the stored value — the later commit would otherwise
        overwrite the DB's current (higher) value with
        max(<stale value>, clamped). func.greatest/func.coalesce reads the
        row's CURRENT value inside the UPDATE itself, so whichever
        transaction commits last still only moves the value up.
        """
        held = rank_for_xp(await ProgressService.xp_for(db, user.family_id, user.id))
        clamped = min(rank, held)
        await db.execute(
            update(User)
            .where(User.id == user.id, User.family_id == user.family_id)
            .values(last_seen_rank=func.greatest(func.coalesce(User.last_seen_rank, 1), clamped))
        )
        await db.commit()

    @staticmethod
    async def progress_for(db: AsyncSession, user: User) -> ProgressResponse:
        if user.role not in KID_ROLES:
            return ProgressResponse(applies=False)
        today, tz = await ProgressService.family_today(db, user.family_id)
        xp = await ProgressService.xp_for(db, user.family_id, user.id)
        rank = rank_for_xp(xp)
        streak = compute_streak(
            await ProgressService.day_states(db, user.family_id, user.id, today, tz), today,
        )
        seen = user.last_seen_rank or 1
        return ProgressResponse(
            applies=True,
            xp=int(xp),
            rank=int(rank),
            rank_floor_xp=int(rank_floor(rank)),
            next_rank_xp=next_rank_xp(rank),
            streak_days=int(streak.days),
            week=[DayEntry(date=d, state=s.value) for d, s in streak.week],
            shield_used=streak.shield_used,
            celebrate_rank=rank if rank > seen else None,
        )
