# UX-D1 Streak + Rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every kid and teen a daily chore streak (with a weekly forgiven miss) and a 10-step rank grown by XP, derived from existing ledgers, shown in the kid header, a progress sheet, a one-time rank-up celebration and the parent hub.

**Architecture:** A backend `ProgressService` with pure rules (rank curve, streak walk) plus family-scoped queries over `point_transactions`, `cash_transactions` and `task_assignments`; two endpoints under `/api/progress`; one nullable column `users.last_seen_rank`; `KidSummary` gains `streak_days`/`rank`. Frontend `lib/progress.ts` owns the rank names and view-model; Astro components render pills, sheet and celebration.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest (backend); Astro 5 + Tailwind v4 + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md`

## Global Constraints

- Backend test command (podman is down locally; bare-metal PG on 5435 + redis are running), run from `backend/`:
  `export TZ=UTC REDIS_URL=redis://localhost:6379/0 UPLOADS_ROOT=/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/uploads TEST_DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test; timeout 900 /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/pytest -q --no-cov -p no:warnings <files> </dev/null`
  Never run the whole backend suite from an implementer (CI runs it); run the named files.
- Frontend commands run from `frontend/` with `</dev/null` and a `timeout`.
- Rank thresholds (backend only): `(0, 100, 300, 600, 1000, 1600, 2500, 3800, 5500, 8000)`.
- XP types: points `task_completed`, `bonus`, `gig_approved` (points > 0); cash `gig_earned` (amount_cents > 0), `amount_cents // 100` per row.
- Streak: family-tz days; due chores = the kid's assignments with `assigned_date = D`, template `is_bonus = false`, `status != cancelled`; done = every due chore has `completed_at` whose family-tz date ≤ D, `completion_grade != 'missed'`, `approval_status != rejected`. First missed day per Monday–Sunday week forgiven (shield); lookback 365 days.
- Every query filters by the kid's `family_id` (multi-tenant rule). Response numbers are plain `int` (never Decimal).
- Rank names (frontend only) exactly as the spec table; kids = role `child`, teens = role `teen`.
- Frontend follows the UX-B3 visual system: ink text on brand fills, `buttonClass`, `text-brand-*-text` for colored text, no emoji in `<h1>`, `hidden` attribute (not class) on kit buttons; the strict guard `test/visual-consistency.test.ts` must stay green.
- Never native alert/confirm/prompt. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Legacy completed chores with `completed_at = NULL`** (rows from before completed_at was written) — a reasonable kid expects old finished days to count, not show as missed. Ruling for the plan (spec is silent): `status = completed` with `completed_at IS NULL` counts as done on time. Pinned by Task 2 test `test_legacy_completed_without_timestamp_counts_done`.
2. **Family timezone vs UTC at the day boundary** — a chore finished at 23:30 local (next day in UTC) must count for its local day. Pinned by Task 2 test `test_completion_late_evening_local_counts_for_that_day`.
3. **A kid with no history at all** (new kid, no ledgers, no assignments) — expects rank 1 "Rookie", streak 0, no crash. Pinned by Task 3 test `test_new_kid_gets_rank_one_streak_zero`.
4. **Progress endpoint down or slow** — the kid home must still render (no pills). Pinned by Task 5's dashboard wiring using `apiFetch` (never throws) + `progressView(null) === null` unit test in Task 4.
5. **Two parents / multiple kids on the hub** — each kid row shows their own streak/rank, computed per kid, never mixed. Pinned by Task 3 test `test_kid_summary_streak_rank_per_kid`.

---

### Task 1: Pure rules — rank curve and streak walk

**Files:**
- Create: `backend/app/services/progress_service.py`
- Test: `backend/tests/test_progress_rules.py`

**Interfaces:**
- Produces: `RANK_THRESHOLDS: tuple[int, ...]`, `MAX_RANK = 10`, `rank_for_xp(xp: int) -> int`, `rank_floor(rank: int) -> int`, `next_rank_xp(rank: int) -> int | None`, `class DayState(str, Enum)` with values `none`, `done`, `missed`, `shield`, `today`, `future`, `@dataclass StreakResult(days: int, week: list[tuple[date, DayState]], shield_used: bool)`, `compute_streak(states: dict[date, DayState], today: date) -> StreakResult` — all in `app/services/progress_service.py`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_progress_rules.py`:

```python
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
```

- [ ] **Step 2: Run — RED**

Run (Global Constraints backend command) with `tests/test_progress_rules.py`.
Expected: collection error `ModuleNotFoundError: No module named 'app.services.progress_service'`.

- [ ] **Step 3: Implement** — `backend/app/services/progress_service.py`:

```python
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
```

- [ ] **Step 4: Run — GREEN**

Run the same command. Expected: all `tests/test_progress_rules.py` pass. (If `test_lookback_is_365_days` returns 366, the walk includes one day too many — fix the rule, not the test: the spec caps the lookback at 365 days.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/progress_service.py backend/tests/test_progress_rules.py
git commit -m "feat(ux-d1): pure streak + rank rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Queries — XP, day states, progress; `last_seen_rank` column

**Files:**
- Modify: `backend/app/services/progress_service.py` (append `ProgressService`), `backend/app/models/user.py` (column)
- Create: `backend/app/schemas/progress.py`, `backend/migrations/versions/2026_09_30_user_last_seen_rank.py`, `backend/tests/test_progress_service.py`

**Interfaces:**
- Consumes: Task 1 rules.
- Produces: `ProgressService.xp_for(db, family_id: UUID, user_id: UUID) -> int`, `ProgressService.day_states(db, family_id: UUID, user_id: UUID, today: date, tz: ZoneInfo) -> dict[date, DayState]`, `ProgressService.family_today(db, family_id) -> tuple[date, ZoneInfo]`, `ProgressService.progress_for(db, user: User) -> ProgressResponse`; `app/schemas/progress.py`: `DayEntry(date: date, state: str)`, `ProgressResponse(applies: bool, xp: int = 0, rank: int = 1, rank_floor_xp: int = 0, next_rank_xp: int | None = None, streak_days: int = 0, week: list[DayEntry] = [], shield_used: bool = False, celebrate_rank: int | None = None)`, `AckRankRequest(rank: int)` with `ge=1, le=10`; `User.last_seen_rank: int | None`.

- [ ] **Step 1: Schema, column, migration** (no behavior yet)

`backend/app/schemas/progress.py`:

```python
"""UX-D1 progress (streak + rank) API shapes. All numbers are plain ints."""
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class DayEntry(BaseModel):
    date: date
    state: str  # none | done | missed | shield | today | future


class ProgressResponse(BaseModel):
    applies: bool
    xp: int = 0
    rank: int = 1
    rank_floor_xp: int = 0
    next_rank_xp: Optional[int] = None
    streak_days: int = 0
    week: list[DayEntry] = Field(default_factory=list)
    shield_used: bool = False
    celebrate_rank: Optional[int] = None


class AckRankRequest(BaseModel):
    rank: int = Field(ge=1, le=10)
```

In `backend/app/models/user.py`, directly after the `gig_trust_streak = Column(...)` block add:

```python
    # UX-D1: highest rank whose one-time celebration the kid has dismissed.
    # NULL = never seen one. Only ever moves up (POST /api/progress/me/ack-rank).
    last_seen_rank = Column(Integer, nullable=True)
```

`backend/migrations/versions/2026_09_30_user_last_seen_rank.py`:

```python
"""users.last_seen_rank for the UX-D1 rank-up celebration

Revision ID: user_last_seen_rank
Revises: mark_stale_reminders_read
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "user_last_seen_rank"
down_revision = "mark_stale_reminders_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_rank", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen_rank")
```

- [ ] **Step 2: Write the failing integration tests** — `backend/tests/test_progress_service.py`:

```python
"""UX-D1 progress queries against the test DB (family-scoped, tz-aware)."""
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models.cash_transaction import CashTransaction, CashTransactionType as CT
from app.models.family import Family
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.progress_service import DayState as S, ProgressService

from conftest import family_local_today


async def _pt(db, kid, typ, points):
    db.add(PointTransaction(type=typ, points=points, user_id=kid.id, family_id=kid.family_id,
                            balance_before=0, balance_after=max(points, 0)))
    await db.commit()


async def _ct(db, kid, typ, cents):
    db.add(CashTransaction(type=typ, amount_cents=cents, user_id=kid.id, family_id=kid.family_id,
                           balance_before=0, balance_after=max(cents, 0)))
    await db.commit()


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True,
                     family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, *, status=AssignmentStatus.COMPLETED, completed_at=None,
                  grade=None, approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=kid.family_id, template_id=template.id, assigned_to=kid.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()),
                       completed_at=completed_at)
    db.add(a)
    await db.commit()
    return a


def _at(day, hour, tz):
    return datetime.combine(day, time(hour, 0), tzinfo=tz).astimezone(timezone.utc)


class TestXp:
    async def test_counts_only_earning_types(self, db_session, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 40)
        await _pt(db_session, kid, PT.BONUS, 10)
        await _pt(db_session, kid, PT.GIG_APPROVED, 5)
        await _pt(db_session, kid, PT.PARENT_ADJUSTMENT, 500)
        await _pt(db_session, kid, PT.REWARD_REDEEMED, -30)
        await _pt(db_session, kid, PT.PENALTY, -20)
        await _ct(db_session, kid, CT.GIG_EARNED, 8050)    # $80.50 -> 80 XP
        await _ct(db_session, kid, CT.ALLOWANCE, 5000)
        await _ct(db_session, kid, CT.PAYOUT, -2000)
        xp = await ProgressService.xp_for(db_session, kid.family_id, kid.id)
        assert xp == 40 + 10 + 5 + 80
        assert isinstance(xp, int)

    async def test_another_familys_rows_never_count(self, db_session, test_child_user):
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        db_session.add(PointTransaction(type=PT.TASK_COMPLETED, points=999, user_id=test_child_user.id,
                                        family_id=other.id, balance_before=0, balance_after=999))
        await db_session.commit()
        assert await ProgressService.xp_for(db_session, test_child_user.family_id, test_child_user.id) == 0


class TestDayStates:
    async def test_done_missed_none_and_bonus_ignored(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 18, tz))
        await _assign(db_session, kid, bonus, y, status=AssignmentStatus.PENDING)  # bonus: ignored
        d2 = today - timedelta(days=2)
        await _assign(db_session, kid, chore, d2, completed_at=_at(d2, 9, tz))
        await _assign(db_session, kid, chore, d2, status=AssignmentStatus.OVERDUE)  # one open -> missed
        d4 = today - timedelta(days=4)
        await _assign(db_session, kid, chore, d4, status=AssignmentStatus.CANCELLED)  # cancelled only -> none
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done
        assert states[d2] == S.missed
        assert states.get(d4, S.none) == S.none
        assert states.get(today - timedelta(days=3), S.none) == S.none

    async def test_missed_grade_and_rejection_count_as_missed(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y, d2 = today - timedelta(days=1), today - timedelta(days=2)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 10, tz), grade="missed")
        await _assign(db_session, kid, chore, d2, completed_at=_at(d2, 10, tz), approval=ApprovalStatus.REJECTED)
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.missed and states[d2] == S.missed

    async def test_completed_after_its_day_is_missed(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        d2 = today - timedelta(days=2)
        await _assign(db_session, kid, chore, d2, completed_at=_at(today - timedelta(days=1), 10, tz))
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[d2] == S.missed

    async def test_completion_late_evening_local_counts_for_that_day(self, db_session, test_family, test_child_user):
        test_family.timezone = "America/Mexico_City"
        await db_session.commit()
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 23, tz))  # next day in UTC
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done

    async def test_legacy_completed_without_timestamp_counts_done(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=None)  # status COMPLETED, no timestamp
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[y] == S.done

    async def test_today_done_vs_open(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        states = await ProgressService.day_states(db_session, test_family.id, kid.id, today, tz)
        assert states[today] == S.today


class TestProgressFor:
    async def test_parent_does_not_apply(self, db_session, test_parent_user):
        r = await ProgressService.progress_for(db_session, test_parent_user)
        assert r.applies is False

    async def test_kid_xp_rank_streak_and_celebrate(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _pt(db_session, kid, PT.TASK_COMPLETED, 350)   # rank 3
        today, tz = await ProgressService.family_today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        y = today - timedelta(days=1)
        await _assign(db_session, kid, chore, y, completed_at=_at(y, 12, tz))
        r = await ProgressService.progress_for(db_session, kid)
        assert r.applies and r.xp == 350 and r.rank == 3
        assert r.rank_floor_xp == 300 and r.next_rank_xp == 600
        assert r.streak_days == 1
        assert len(r.week) == 7
        assert r.celebrate_rank == 3        # never seen a celebration
        kid.last_seen_rank = 3
        await db_session.commit()
        r2 = await ProgressService.progress_for(db_session, kid)
        assert r2.celebrate_rank is None

    async def test_rank_one_never_celebrates(self, db_session, test_child_user):
        r = await ProgressService.progress_for(db_session, test_child_user)
        assert r.rank == 1 and r.celebrate_rank is None
```

- [ ] **Step 3: Run — RED**

Run the backend command with `tests/test_progress_service.py`.
Expected: FAIL — `AttributeError: ... has no attribute 'ProgressService'` (or ImportError on `ProgressService`).

- [ ] **Step 4: Implement** — append to `backend/app/services/progress_service.py`:

```python
# ── Queries (family-scoped) ──────────────────────────────────────────────
from datetime import datetime  # noqa: E402
from uuid import UUID  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from sqlalchemy import and_, func, select  # noqa: E402
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
        points = (await db.execute(
            select(func.coalesce(func.sum(PointTransaction.points), 0)).where(
                PointTransaction.family_id == family_id,
                PointTransaction.user_id == user_id,
                PointTransaction.points > 0,
                PointTransaction.type.in_(XP_POINT_TYPES),
            )
        )).scalar()
        pesos = (await db.execute(
            select(func.coalesce(func.sum(CashTransaction.amount_cents // 100), 0)).where(
                CashTransaction.family_id == family_id,
                CashTransaction.user_id == user_id,
                CashTransaction.amount_cents > 0,
                CashTransaction.type == CashTransactionType.GIG_EARNED,
            )
        )).scalar()
        return int(points or 0) + int(pesos or 0)

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
```

(Keep the imports at the bottom of the rules section as shown so the pure rules above stay import-light; ruff's `E402` is silenced per line. If ruff config rejects the `noqa` style, move the imports to the top of the file instead — behavior is identical.)

- [ ] **Step 5: Run — GREEN**

Run the backend command with `tests/test_progress_service.py tests/test_progress_rules.py`. Expected: all pass.
Then from `backend/`: `/Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/ruff check app` → `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/progress_service.py backend/app/schemas/progress.py backend/app/models/user.py backend/migrations/versions/2026_09_30_user_last_seen_rank.py backend/tests/test_progress_service.py
git commit -m "feat(ux-d1): progress queries (XP from ledgers, tz-aware day states) + users.last_seen_rank

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: API endpoints + parent hub fields

**Files:**
- Create: `backend/app/api/routes/progress.py`, `backend/tests/test_progress_api.py`
- Modify: `backend/app/main.py` (router import + `include_router`), `backend/app/schemas/oversight.py` (`KidSummary`), `backend/app/services/oversight_service.py` (fill the new fields)

**Interfaces:**
- Consumes: `ProgressService.progress_for`, `ProgressService.xp_for`, `ProgressService.day_states`, `ProgressService.family_today`, `rank_for_xp`, `compute_streak`, `AckRankRequest`, `ProgressResponse`.
- Produces: `GET /api/progress/me` → `ProgressResponse`; `POST /api/progress/me/ack-rank` → 204; `KidSummary.streak_days: int = 0`, `KidSummary.rank: int = 1`.

- [ ] **Step 1: Failing tests** — `backend/tests/test_progress_api.py`:

```python
"""UX-D1 progress endpoints + parent hub fields."""
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.services.oversight_service import OversightService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _xp(db, kid, points):
    db.add(PointTransaction(type=PT.TASK_COMPLETED, points=points, user_id=kid.id,
                            family_id=kid.family_id, balance_before=0, balance_after=points))
    await db.commit()


class TestMe:
    async def test_new_kid_gets_rank_one_streak_zero(self, client, test_child_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200
        body = r.json()
        assert body["applies"] is True and body["rank"] == 1 and body["streak_days"] == 0
        assert body["celebrate_rank"] is None and len(body["week"]) == 7

    async def test_teen_applies(self, client, test_teen_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is True

    async def test_parent_does_not_apply(self, client, test_parent_user):
        r = await client.get("/api/progress/me", headers=await _login(client, "parent@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is False

    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/me")).status_code in (401, 403)


class TestAck:
    async def test_ack_moves_up_only_and_never_past_held_rank(self, client, db_session, test_child_user):
        await _xp(db_session, test_child_user, 650)  # rank 4
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] == 4
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 9}, headers=h)).status_code == 204
        await db_session.refresh(test_child_user)
        assert test_child_user.last_seen_rank == 4          # clamped to the held rank
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 2}, headers=h)).status_code == 204
        await db_session.refresh(test_child_user)
        assert test_child_user.last_seen_rank == 4          # never moves down
        assert (await client.get("/api/progress/me", headers=h)).json()["celebrate_rank"] is None

    async def test_ack_bounds_and_parent(self, client, test_child_user, test_parent_user):
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 0}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 11}, headers=h)).status_code == 422
        hp = await _login(client, "parent@test.com")
        assert (await client.post("/api/progress/me/ack-rank", json={"rank": 1}, headers=hp)).status_code == 404


class TestKidSummary:
    async def test_kid_summary_streak_rank_per_kid(self, db_session, test_family, test_child_user, test_teen_user):
        await _xp(db_session, test_child_user, 1200)   # rank 5
        await _xp(db_session, test_teen_user, 150)     # rank 2
        summary = await OversightService.get_summary(db_session, test_family.id)
        by_id = {m.user_id: m for m in summary.members}
        assert by_id[test_child_user.id].rank == 5
        assert by_id[test_teen_user.id].rank == 2
        assert isinstance(by_id[test_child_user.id].streak_days, int)
```

- [ ] **Step 2: Run — RED** (backend command, `tests/test_progress_api.py`). Expected: 404s on `/api/progress/me` and `AttributeError`/`KeyError` on `rank`.

- [ ] **Step 3: Implement the routes** — `backend/app/api/routes/progress.py`:

```python
"""UX-D1 progress: the signed-in kid's streak + rank, and the rank-up ack."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.progress import AckRankRequest, ProgressResponse
from app.services.progress_service import KID_ROLES, ProgressService, rank_for_xp

router = APIRouter()


@router.get("/me", response_model=ProgressResponse)
async def my_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    return await ProgressService.progress_for(db, current_user)


@router.post("/me/ack-rank", status_code=status.HTTP_204_NO_CONTENT)
async def ack_rank(
    data: AckRankRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    held = rank_for_xp(await ProgressService.xp_for(db, current_user.family_id, current_user.id))
    current_user.last_seen_rank = max(current_user.last_seen_rank or 1, min(data.rank, held))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

In `backend/app/main.py`: add `progress` to the `from app.api.routes import oversight, onboarding` line (→ `from app.api.routes import oversight, onboarding, progress`), and after the `app.include_router(oversight.router, ...)` line add:

```python
app.include_router(progress.router, prefix="/api/progress", tags=["Progress"])
```

- [ ] **Step 4: Parent hub fields** — in `backend/app/schemas/oversight.py` `KidSummary`, after `last_nudged_at: Optional[datetime] = None` add:

```python
    # UX-D1: same values as the kid's own /api/progress/me.
    streak_days: int = 0
    rank: int = 1
```

In `backend/app/services/oversight_service.py` `get_summary`: import `from app.services.progress_service import ProgressService, compute_streak, rank_for_xp` at the top; before the loop that builds `members`, compute `today, tz = await ProgressService.family_today(db, family_id)`; inside the per-kid loop compute

```python
                xp = await ProgressService.xp_for(db, family_id, kid.id)
                streak = compute_streak(
                    await ProgressService.day_states(db, family_id, kid.id, today, tz), today,
                )
```

and pass `streak_days=int(streak.days), rank=int(rank_for_xp(xp)),` into the `KidSummary(...)` call (after `last_nudged_at=...`).

- [ ] **Step 5: Run — GREEN**

Run the backend command with `tests/test_progress_api.py tests/test_progress_service.py tests/test_progress_rules.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py`. Expected: all pass. `ruff check app` → clean.

- [ ] **Step 6: Migration round-trip** (CI does it too; catch it early):

From `backend/`, with the same env exports: `DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/alembic upgrade head </dev/null 2>&1 | tail -2` → ends at `user_last_seen_rank`. (Do not run the downgrade command from the shell — a pre-bash hook blocks that phrase; CI exercises the round-trip.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/progress.py backend/app/main.py backend/app/schemas/oversight.py backend/app/services/oversight_service.py backend/tests/test_progress_api.py
git commit -m "feat(ux-d1): /api/progress/me + ack-rank; parent hub streak/rank

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `lib/progress.ts` — names and view-model

**Files:**
- Create: `frontend/src/lib/progress.ts`, `frontend/test/progress.test.ts`

**Interfaces:**
- Consumes: the `/api/progress/me` JSON shape (Task 3).
- Produces: `type Skin = "child" | "teen"`, `type DayStateName = "none" | "done" | "missed" | "shield" | "today" | "future"`, `RANK_NAMES`, `rankName(rank: number, skin: Skin, lang: "es" | "en"): string`, `interface ProgressView { streakLabel: string; rankLabel: string; barPct: number; toNextLabel: string; ladder: { rank: number; name: string; state: "done" | "current" | "locked" }[]; week: { label: string; state: DayStateName }[]; celebrateRank: number | null; celebrateName: string | null }`, `progressView(resp: any, skin: Skin, lang: "es" | "en"): ProgressView | null`, `progressLine(kid: any, lang: "es" | "en"): string | null` (parent hub row text).

- [ ] **Step 1: Failing tests** — `frontend/test/progress.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { progressLine, progressView, rankName, RANK_NAMES } from "../src/lib/progress";

const resp = (over: Record<string, unknown> = {}) => ({
    applies: true, xp: 450, rank: 3, rank_floor_xp: 300, next_rank_xp: 600, streak_days: 5,
    shield_used: true, celebrate_rank: null,
    week: [
        { date: "2026-09-28", state: "done" }, { date: "2026-09-29", state: "shield" },
        { date: "2026-09-30", state: "done" }, { date: "2026-10-01", state: "today" },
        { date: "2026-10-02", state: "future" }, { date: "2026-10-03", state: "future" },
        { date: "2026-10-04", state: "future" },
    ],
    ...over,
});

describe("rankName", () => {
    it("has 10 names per skin and language", () => {
        for (const skin of ["child", "teen"] as const) for (const lang of ["es", "en"] as const) {
            expect(RANK_NAMES[skin][lang]).toHaveLength(10);
        }
    });
    it("uses the spec names", () => {
        expect(rankName(4, "child", "es")).toBe("Estrella");
        expect(rankName(4, "teen", "en")).toBe("Pro");
        expect(rankName(10, "child", "en")).toBe("Legend");
        expect(rankName(2, "teen", "es")).toBe("Colaborador");
    });
    it("clamps out-of-range ranks", () => {
        expect(rankName(0, "child", "en")).toBe("Rookie");
        expect(rankName(99, "teen", "es")).toBe("Leyenda");
    });
});

describe("progressView", () => {
    it("is null when progress does not apply or is missing", () => {
        expect(progressView(null, "child", "es")).toBeNull();
        expect(progressView({ applies: false }, "child", "es")).toBeNull();
    });
    it("labels, bar and next rank", () => {
        const v = progressView(resp(), "child", "es")!;
        expect(v.streakLabel).toBe("🔥 5 días");
        expect(v.rankLabel).toBe("Explorador · 3/10");
        expect(v.barPct).toBe(50);
        expect(v.toNextLabel).toBe("150 XP para Estrella");
    });
    it("singular day and English", () => {
        const v = progressView(resp({ streak_days: 1 }), "teen", "en")!;
        expect(v.streakLabel).toBe("🔥 1 day");
        expect(v.rankLabel).toBe("Reliable · 3/10");
    });
    it("top rank has a full bar and no next", () => {
        const v = progressView(resp({ rank: 10, xp: 9000, rank_floor_xp: 8000, next_rank_xp: null }), "child", "en")!;
        expect(v.barPct).toBe(100);
        expect(v.toNextLabel).toBe("Top rank!");
    });
    it("ladder states and week labels", () => {
        const v = progressView(resp(), "child", "en")!;
        expect(v.ladder.map((r) => r.state)).toEqual(["done", "done", "current", ...Array(7).fill("locked")]);
        expect(v.week.map((d) => d.label)).toEqual(["M", "T", "W", "T", "F", "S", "S"]);
        expect(v.week.map((d) => d.state)).toEqual(["done", "shield", "done", "today", "future", "future", "future"]);
    });
    it("celebration name follows the skin", () => {
        const v = progressView(resp({ celebrate_rank: 4 }), "teen", "es")!;
        expect(v.celebrateRank).toBe(4);
        expect(v.celebrateName).toBe("Pro");
    });
});

describe("progressLine (parent hub)", () => {
    it("streak and rank name by the kid's role", () => {
        expect(progressLine({ role: "child", streak_days: 5, rank: 4 }, "es")).toBe("🔥 5 · Estrella");
        expect(progressLine({ role: "teen", streak_days: 0, rank: 4 }, "en")).toBe("🔥 0 · Pro");
    });
    it("null when the fields are missing", () => {
        expect(progressLine({ role: "child" }, "es")).toBeNull();
    });
});
```

- [ ] **Step 2: Run — RED**: `timeout 300 npx vitest run test/progress.test.ts </dev/null` → fails to resolve `../src/lib/progress`.

- [ ] **Step 3: Implement** — `frontend/src/lib/progress.ts`:

```ts
/**
 * UX-D1 progression view-model: rank names (the ONLY copy — thresholds live in
 * the backend) and the shapes the kid header, progress sheet, rank-up
 * celebration and parent hub render.
 */
export type Skin = "child" | "teen";
export type DayStateName = "none" | "done" | "missed" | "shield" | "today" | "future";

export const RANK_NAMES: Record<Skin, Record<"es" | "en", readonly string[]>> = {
    child: {
        es: ["Novato", "Ayudante", "Explorador", "Estrella", "Súper Ayudante", "Campeón", "Héroe", "Maestro", "Gran Maestro", "Leyenda"],
        en: ["Rookie", "Helper", "Explorer", "Star", "Super Helper", "Champion", "Hero", "Master", "Grand Master", "Legend"],
    },
    teen: {
        es: ["Novato", "Colaborador", "Confiable", "Pro", "Experto", "Especialista", "Capitán", "Élite", "Maestro", "Leyenda"],
        en: ["Rookie", "Contributor", "Reliable", "Pro", "Expert", "Specialist", "Captain", "Elite", "Master", "Legend"],
    },
};

const MAX_RANK = 10;
const clampRank = (r: number) => Math.max(1, Math.min(MAX_RANK, Math.trunc(Number(r) || 1)));

export function rankName(rank: number, skin: Skin, lang: "es" | "en"): string {
    return RANK_NAMES[skin][lang][clampRank(rank) - 1];
}

export interface ProgressView {
    streakLabel: string;
    rankLabel: string;
    barPct: number;
    toNextLabel: string;
    ladder: { rank: number; name: string; state: "done" | "current" | "locked" }[];
    week: { label: string; state: DayStateName }[];
    celebrateRank: number | null;
    celebrateName: string | null;
}

const DAY_LABELS = { es: ["L", "M", "M", "J", "V", "S", "D"], en: ["M", "T", "W", "T", "F", "S", "S"] };

export function progressView(resp: any, skin: Skin, lang: "es" | "en"): ProgressView | null {
    if (!resp || resp.applies !== true) return null;
    const es = lang === "es";
    const rank = clampRank(resp.rank);
    const xp = Number(resp.xp) || 0;
    const floor = Number(resp.rank_floor_xp) || 0;
    const next = resp.next_rank_xp == null ? null : Number(resp.next_rank_xp);
    const days = Number(resp.streak_days) || 0;
    const barPct = next == null ? 100 : Math.max(0, Math.min(100, Math.round(((xp - floor) / Math.max(1, next - floor)) * 100)));
    const toNextLabel = next == null
        ? (es ? "¡Rango máximo!" : "Top rank!")
        : es ? `${next - xp} XP para ${rankName(rank + 1, skin, lang)}` : `${next - xp} XP to ${rankName(rank + 1, skin, lang)}`;
    const celebrate = resp.celebrate_rank == null ? null : clampRank(resp.celebrate_rank);
    const week = Array.isArray(resp.week) ? resp.week.slice(0, 7) : [];
    return {
        streakLabel: es ? `🔥 ${days} ${days === 1 ? "día" : "días"}` : `🔥 ${days} ${days === 1 ? "day" : "days"}`,
        rankLabel: `${rankName(rank, skin, lang)} · ${rank}/${MAX_RANK}`,
        barPct,
        toNextLabel,
        ladder: Array.from({ length: MAX_RANK }, (_, i) => ({
            rank: i + 1,
            name: rankName(i + 1, skin, lang),
            state: i + 1 < rank ? "done" : i + 1 === rank ? "current" : "locked",
        })),
        week: week.map((d: any, i: number) => ({ label: DAY_LABELS[lang][i], state: String(d?.state ?? "none") as DayStateName })),
        celebrateRank: celebrate,
        celebrateName: celebrate == null ? null : rankName(celebrate, skin, lang),
    };
}

export function progressLine(kid: any, lang: "es" | "en"): string | null {
    if (kid?.rank == null || kid?.streak_days == null) return null;
    const skin: Skin = kid.role === "teen" ? "teen" : "child";
    return `🔥 ${Number(kid.streak_days) || 0} · ${rankName(kid.rank, skin, lang)}`;
}
```

- [ ] **Step 4: Run — GREEN**: `timeout 300 npx vitest run test/progress.test.ts </dev/null` → all pass; then `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/progress.ts frontend/test/progress.test.ts
git commit -m "feat(ux-d1): progress view-model and rank names (kids/teens, es/en)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Kid header pills, progress sheet, rank-up celebration, parent row

**Files:**
- Modify: `frontend/src/components/home/KidHeader.astro`, `frontend/src/pages/dashboard.astro`, `frontend/src/lib/parentHub.ts` (`KidRowView` + `kidRowView`), `frontend/src/components/home/KidRow.astro`, `frontend/test/parent-hub.test.ts`
- Create: `frontend/src/components/home/ProgressSheet.astro`, `frontend/src/components/home/RankUpCelebration.astro`, `frontend/src/pages/api/progress/[...path].ts` (same-origin proxy — there is no catch-all; each backend area has its own)

**Interfaces:**
- Consumes: `progressView`, `ProgressView`, `progressLine` (Task 4); `buttonClass` (`lib/buttonClasses.ts`); `fireConfetti` (`lib/celebrate.ts`).
- Produces: `KidHeader` prop `progress?: ProgressView | null`; `KidRowView.progressLine: string | null`.

- [ ] **Step 1: Failing parent-hub test** — append to `frontend/test/parent-hub.test.ts`:

```ts
import { kidRowView as _kidRowViewD1 } from "../src/lib/parentHub";

describe("kidRowView progress line (UX-D1)", () => {
    it("shows streak and rank name for the kid's role", () => {
        const v = _kidRowViewD1({ user_id: "k1", name: "Sofía", role: "child", streak_days: 5, rank: 4 }, null, new Date(), "es");
        expect(v.progressLine).toBe("🔥 5 · Estrella");
    });
    it("is null without progress fields", () => {
        const v = _kidRowViewD1({ user_id: "k1", name: "Sofía", role: "child" }, null, new Date(), "es");
        expect(v.progressLine).toBeNull();
    });
});
```

(If `describe`/`expect` are not yet imported in that file under those names, reuse its existing import line; if `kidRowView` is already imported, use that name instead of the alias.)

Run: `timeout 300 npx vitest run test/parent-hub.test.ts </dev/null` → FAIL (`progressLine` undefined).

- [ ] **Step 2: Parent row** — in `frontend/src/lib/parentHub.ts`: import `import { progressLine } from "./progress";`, add `progressLine: string | null;` to `KidRowView`, and in `kidRowView`'s returned object add `progressLine: progressLine(kid, lang),`. In `frontend/src/components/home/KidRow.astro`, directly under the element that renders the kid's name, add:

```astro
{view.progressLine && <p class="text-xs font-bold text-brand-ink-soft" data-kid-progress>{view.progressLine}</p>}
```

Run the parent-hub test → PASS.

- [ ] **Step 3: Header pills** — in `frontend/src/components/home/KidHeader.astro`: import `import type { ProgressView } from "../../lib/progress";`, add `progress?: ProgressView | null;` to `Props`, destructure `progress = null`, add in the frontmatter:

```ts
const pillCls = skin === "teen" ? "bg-white/10 border-white/25" : "bg-white/40 border-brand-ink/20";
const trackCls = skin === "teen" ? "bg-white/15" : "bg-brand-ink/15";
const fillCls = skin === "teen" ? "bg-brand-mint" : "bg-brand-ink";
```

and, right after the first `<div class="flex items-center justify-between gap-3">…</div>` (name + balance row), insert:

```astro
    {progress && (
        <div class="mt-2" data-progress-row>
            <div class="flex flex-wrap gap-2">
                <button type="button" data-progress-open class={`rounded-full border px-3 py-1 text-xs font-extrabold ${pillCls}`}>
                    {progress.streakLabel}
                </button>
                <button type="button" data-progress-open class={`rounded-full border px-3 py-1 text-xs font-extrabold ${pillCls}`}>
                    {progress.rankLabel}
                </button>
            </div>
            <div class={`mt-2 h-1.5 rounded-full overflow-hidden ${trackCls}`} role="img"
                 aria-label={progress.toNextLabel}>
                <div class={`h-full ${fillCls}`} style={`width:${progress.barPct}%`}></div>
            </div>
        </div>
    )}
```

(Text color is inherited from the header — ink on the sky kid header, white on the teen dark skin — so no `text-*` class is added; the visual guard stays green.)

- [ ] **Step 4: Progress sheet** — `frontend/src/components/home/ProgressSheet.astro`:

```astro
---
/**
 * UX-D1 progress sheet: rank ladder, XP to next, this week's streak strip.
 * Opened by any [data-progress-open] on the page.
 */
import type { ProgressView } from "../../lib/progress";
import { buttonClass } from "../../lib/buttonClasses";

interface Props {
    progress: ProgressView;
    lang: "es" | "en";
}
const { progress, lang } = Astro.props;
const es = lang === "es";
const dayCls: Record<string, string> = {
    done: "bg-brand-mint border-brand-ink text-brand-ink",
    shield: "bg-brand-sun border-brand-ink text-brand-ink",
    missed: "bg-white border-brand-ink/30 text-brand-ink-soft line-through",
    today: "bg-white border-brand-ink text-brand-ink",
    future: "bg-white border-brand-ink/15 text-brand-ink-soft",
    none: "bg-brand-cream-deep border-brand-ink/15 text-brand-ink-soft",
};
const dayMark: Record<string, string> = { done: "✓", shield: "🛡️", missed: "✕", today: "•", future: "", none: "–" };
---

<dialog id="progress-sheet" aria-labelledby="progress-sheet-title"
        class="m-0 mt-auto w-full max-w-md mx-auto rounded-t-[var(--radius-tile)] bg-brand-cream text-brand-ink p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] border-t-2 border-brand-ink backdrop:bg-brand-ink/50 z-[60]">
    <h2 id="progress-sheet-title" class="font-display text-xl font-extrabold">{progress.rankLabel}</h2>
    <p class="text-sm text-brand-ink-soft">{progress.toNextLabel}</p>

    <h3 class="mt-4 text-xs font-extrabold uppercase tracking-wide">{es ? "Esta semana" : "This week"} · {progress.streakLabel}</h3>
    <ol class="mt-2 grid grid-cols-7 gap-1.5">
        {progress.week.map((d) => (
            <li class={`flex flex-col items-center rounded-xl border-2 py-1.5 text-xs font-bold ${dayCls[d.state] ?? dayCls.none}`}>
                <span>{d.label}</span><span aria-hidden="true">{dayMark[d.state] ?? ""}</span>
            </li>
        ))}
    </ol>
    <p class="mt-2 text-xs text-brand-ink-soft">
        {es ? "Termina todas tus tareas del día. Tienes 1 día de perdón por semana." : "Finish all your chores each day. You get 1 free miss per week."}
    </p>

    <h3 class="mt-4 text-xs font-extrabold uppercase tracking-wide">{es ? "Rangos" : "Ranks"}</h3>
    <ol class="mt-2 space-y-1">
        {progress.ladder.map((r) => (
            <li class={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm ${r.state === "current" ? "bg-brand-sun border-2 border-brand-ink font-extrabold" : r.state === "done" ? "font-bold" : "text-brand-ink-soft"}`}>
                <span class="w-6 text-right">{r.rank}</span><span class="flex-1">{r.name}</span>
                <span aria-hidden="true">{r.state === "done" ? "✓" : r.state === "locked" ? "🔒" : "★"}</span>
            </li>
        ))}
    </ol>

    <form method="dialog" class="mt-4">
        <button class={`${buttonClass("ghost", "md")} w-full`}>{es ? "Cerrar" : "Close"}</button>
    </form>
</dialog>

<script>
    document.addEventListener("click", (e) => {
        const t = (e.target as HTMLElement | null)?.closest("[data-progress-open]");
        if (!t) return;
        const dlg = document.getElementById("progress-sheet") as HTMLDialogElement | null;
        dlg?.showModal();
    });
</script>
```

- [ ] **Step 5: Rank-up celebration** — `frontend/src/components/home/RankUpCelebration.astro`:

```astro
---
/**
 * UX-D1 one-time rank-up celebration. Rendered only when /api/progress/me
 * returns celebrate_rank; dismissing POSTs the ack so it never shows again.
 */
import { buttonClass } from "../../lib/buttonClasses";

interface Props {
    rank: number;
    name: string;
    lang: "es" | "en";
}
const { rank, name, lang } = Astro.props;
const es = lang === "es";
---

<div id="rank-up" data-rank={rank} role="dialog" aria-modal="true" aria-labelledby="rank-up-title"
     class="fixed inset-0 z-[60] flex items-center justify-center bg-brand-ink/60 p-6">
    <div class="w-full max-w-sm rounded-[var(--radius-tile)] border-2 border-brand-ink bg-brand-cream p-6 text-center shadow-[var(--shadow-pop)]">
        <p class="text-sm font-bold text-brand-ink-soft">{es ? "¡Subiste de rango!" : "You ranked up!"}</p>
        <p id="rank-up-title" class="mt-1 font-display text-3xl font-extrabold text-brand-ink">
            {es ? `¡Ahora eres ${name}!` : `You're now ${name}!`}
        </p>
        <p class="mt-1 text-sm text-brand-ink-soft">{es ? `Rango ${rank} de 10` : `Rank ${rank} of 10`}</p>
        <button type="button" data-rank-up-ok class={`${buttonClass("primary", "lg")} mt-5 w-full`}>
            {es ? "¡Genial!" : "Awesome!"}
        </button>
    </div>
</div>

<script>
    import { fireConfetti } from "../../lib/celebrate";

    const box = document.getElementById("rank-up");
    if (box) {
        fireConfetti();
        box.querySelector("[data-rank-up-ok]")?.addEventListener("click", () => {
            const rank = Number(box.dataset.rank);
            box.remove();
            fetch("/api/progress/me/ack-rank", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ rank }),
            }).catch(() => {});
        });
    }
</script>
```

- [ ] **Step 5b: Same-origin proxy** — `frontend/src/pages/api/progress/[...path].ts` (the celebration's browser POST goes through it; SSR `apiFetch` calls the backend directly):

```ts
import { createApiProxy } from "../../../lib/server/proxy";

export const { GET, POST, PUT, DELETE, PATCH } = createApiProxy({ name: "progress" });
```

- [ ] **Step 6: Wire the dashboard** — in `frontend/src/pages/dashboard.astro`:
  - imports: `import ProgressSheet from "../components/home/ProgressSheet.astro";`, `import RankUpCelebration from "../components/home/RankUpCelebration.astro";`, `import { progressView } from "../lib/progress";`
  - add `apiFetch<any>("/api/progress/me", { token }),` as a 7th entry of the second `Promise.all` (the one with `paycheck`), destructured as `{ data: progressResp }`;
  - after it: `const progress = progressView(progressResp, skin, lang);`
  - pass `progress={progress}` to `<KidHeader … />`;
  - right after `<KidHome … />` add:

```astro
    {progress && <ProgressSheet progress={progress} lang={lang} />}
    {progress?.celebrateRank && progress.celebrateName && (
        <RankUpCelebration rank={progress.celebrateRank} name={progress.celebrateName} lang={lang} />
    )}
```

- [ ] **Step 7: Verify** (from `frontend/`):
  - `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass (incl. the strict visual guard).
  - `timeout 900 npx astro check </dev/null > /tmp/d1-check.log 2>&1; echo exit=$?; grep -A2 'Result' /tmp/d1-check.log | tail -3` → `exit=0`, `0 errors`.
  - `timeout 900 npm run build </dev/null > /tmp/d1-build.log 2>&1; echo exit=$?; tail -1 /tmp/d1-build.log` → `exit=0`, `Complete!`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/home frontend/src/pages/dashboard.astro frontend/src/pages/api/progress frontend/src/lib/parentHub.ts frontend/test/parent-hub.test.ts
git commit -m "feat(ux-d1): streak + rank pills, progress sheet, rank-up celebration, parent row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Docs + full verification

**Files:**
- Modify: `CLAUDE.md` (repo root — "Additional domains" table), `docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md` (Status)

- [ ] **Step 1: CLAUDE.md** — add a row to the "Additional domains" table, after the **Pet** row:

```markdown
| **Progress** (UX-D1) | `/api/progress` | Kid/teen daily chore **streak** (all non-bonus chores done by end of day, family tz; first miss per Mon–Sun week forgiven 🛡️) and 10-step **rank** from XP = earning points (`task_completed`/`bonus`/`gig_approved`) + gig pesos (`gig_earned` ÷ 100). Derived from ledgers on read — no stored counters; only `users.last_seen_rank` (one-time rank-up celebration). Thresholds in `progress_service.py`; names only in `frontend/src/lib/progress.ts`. Independent of the pet. |
```

- [ ] **Step 2: Spec status** → `**Status:** approved 2026-09-30; implemented on feat/ux-d1-streak-rank`.

- [ ] **Step 3: Verify**
  - Backend: the Global Constraints command with `tests/test_progress_rules.py tests/test_progress_service.py tests/test_progress_api.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py tests/test_family_cup.py` → all pass; `ruff check app` clean.
  - Frontend: vitest all pass; `astro check` 0 errors; build Complete.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-30-ux-d1-streak-rank-design.md
git commit -m "docs(ux-d1): progress domain in CLAUDE.md; spec status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: After deploy** — demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` at 390 px: as `sofia.demo@agent-ia.mx` (child) and `diego.demo@agent-ia.mx` (teen) — pills, sheet opens, celebration shows once then not again; as `mariana.demo@agent-ia.mx` — each kid row shows `🔥 N · Rank`.
