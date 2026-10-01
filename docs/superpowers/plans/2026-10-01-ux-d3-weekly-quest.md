# UX-D3 Weekly Quest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every kid and teen one personal quest per week — picked by rotation, sized to their own recent weeks — with a points bonus paid once when the goal is reached, shown as a card on the kid home and a chip on the parent hub, and controlled by one family setting.

**Architecture:** Like D2 badges: progress is derived on read; only the week's quest (type, target, bonus, paid/seen marks) is stored, in a new `weekly_quests` table. A backend `QuestService` (pure rules + family-scoped queries) creates the quest and pays the bonus inside `GET /api/progress/quest`; `POST /api/progress/quest/ack` marks the done moment seen. A new `families.quest_bonus_points` setting (default 20, 0 = off) rides the existing family update. Frontend `lib/quest.ts` owns the copy and view-model; `QuestCard.astro` renders it under the task deck.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest (backend); Astro 5 + Tailwind v4 + vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-10-01-ux-d3-weekly-quest-design.md`

## Global Constraints

- Work in the worktree `/Users/jc/dev-2026/AgentIA/family-task-manager/.claude/worktrees/ux-d3-weekly-quest` (branch `feat/ux-d3-weekly-quest`). Never `cd` to the main checkout.
- Backend test command (podman is down locally; bare-metal PG on 5435 + redis are running), run from the worktree's `backend/`:
  `export TZ=UTC REDIS_URL=redis://localhost:6379/0 UPLOADS_ROOT=/private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/uploads TEST_DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test; timeout 900 /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/pytest -q --no-cov -p no:warnings <files> </dev/null`
  Never run the whole backend suite from an implementer (CI runs it); run the named files. Never run two pytest processes at once (they share the test DB).
- Backend lint: `/opt/homebrew/bin/ruff check app` from `backend/` (the venv has no ruff). Zero findings.
- Frontend commands run from the worktree's `frontend/` with `</dev/null` and a `timeout`. The worktree has no `node_modules`: Task 5 Step 1 runs `npm ci` once.
- Quest catalog, in rotation order — key: default goal: `on_time` 3 · `extra_mile` 1 · `perfect_days` 2 · `go_getter` 1.
- A week is Monday–Sunday in the family's timezone. Kids and teens only (`KID_ROLES` from `progress_service.py`).
- Counting rule (strict): an assignment counts when `status = completed`, it is not graded `missed`, and `approval_status` is `none` or `approved`. Pending review and rejected never count. "On time" = `completed_at` (family tz) on or before `assigned_date`; a completed row with no `completed_at` is on time.
- The bonus is `families.quest_bonus_points` (default 20, range 0–500) copied onto the quest row at creation; `0` switches quests off (nothing created, nothing paid, `applies: false`). The bonus is paid exactly once per quest and never taken back.
- Every query filters by `family_id` AND the kid's user id (multi-tenant rule). Response numbers are plain `int`.
- Any new table with a `family_id` must be registered in `backend/app/services/family_export_service.py` (`EXPORTED_FAMILY_TABLES`), or `tests/test_family_delete_export.py` fails.
- Tests must pass on any weekday: build dates from the family's "today", never from a hardcoded calendar date, except in the pure rule tests, which pass `today` explicitly.
- Frontend follows the UX-B3 visual system: ink text on brand fills, `buttonClass` for buttons, `text-brand-*-text` for colored text, no emoji in `<h1>`, no new color tokens, the `hidden` ATTRIBUTE (never the `hidden` class) to hide elements; the strict guard `test/visual-consistency.test.ts` must stay green. Never native `alert`/`confirm`/`prompt`.
- The quest's done moment is NOT a modal. No `<dialog>` in this plan.
- Do not type the Alembic step-back command in any shell command (a pre-bash hook blocks that phrase); CI exercises the migration round-trip.
- Commit trailer: use the attribution line your own session instructs; if you have none, `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **The first read of the week happens before any chore exists** (Monday 6 am, before the shuffle) — expects no quest and no error, and a quest to appear on a later read once work exists. Pinned by Task 3 `test_no_quest_until_something_qualifies_then_it_is_created`.
2. **The goal is reached by two requests at once** (two tabs, or the live refresh racing a page load) — expects the bonus exactly once. Pinned by Task 3 `test_settle_twice_pays_once` (drives the guarded UPDATE directly).
3. **The kid finishes on Sunday night, or a parent approves late, and the app is next opened the following week** — expects the bonus to still arrive. Pinned by Task 3 `test_last_weeks_quest_is_paid_on_this_weeks_read`.
4. **A parent switches quests off (bonus 0) while a quest is in flight** — expects no payment and no card from that moment. Pinned by Task 3 `test_bonus_zero_stops_an_in_flight_quest`.
5. **The quest call fails or is slow** — expects the kid home to render without the card. Pinned by Task 5 `returns null without a usable response` and Task 6's structure test that the card renders only behind the view.

---

### Task 1: Pure quest rules

**Files:**
- Create: `backend/app/services/quest_service.py` (pure rules only in this task)
- Test: `backend/tests/test_quest_rules.py`

**Interfaces:**
- Consumes: `ApprovalStatus`, `AssignmentStatus` from `app/models/task_assignment.py`.
- Produces (all in `app/services/quest_service.py`): `QUESTS: dict[str, int]` (rotation order → default goal); `OPEN_ENDED = ("extra_mile", "go_getter")`; `OPEN_ENDED_CAP = 7`; `HISTORY_WEEKS = 4`; `week_monday(d: date) -> date`; `rotation(week_start: date, user_id: UUID) -> list[str]`; `size_target(default: int, history_total: int, done: int, possible: int | None) -> int | None`; `@dataclass(frozen=True) ChoreRow(assigned_date, status, completed_at, grade, approval, is_bonus)`; `chore_state(row: ChoreRow, today: date, tz: ZoneInfo) -> str` (`"yes"` / `"maybe"` / `"no"`); `@dataclass(frozen=True) WeekStats(done: dict[str, int], possible: dict[str, int])`; `week_stats(rows: list[ChoreRow], gigs_approved: int, today: date, tz: ZoneInfo) -> WeekStats`; `pick_quest(order: list[str], stats: WeekStats, history: dict[str, int], offered: dict[str, bool]) -> tuple[str, int] | None`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_quest_rules.py`:

```python
"""UX-D3 pure weekly-quest rules (no DB)."""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models.task_assignment import ApprovalStatus as A, AssignmentStatus as S
from app.services.quest_service import (
    OPEN_ENDED_CAP,
    QUESTS,
    ChoreRow,
    WeekStats,
    chore_state,
    pick_quest,
    rotation,
    size_target,
    week_monday,
    week_stats,
)

UTC = ZoneInfo("UTC")
MON = date(2026, 9, 28)          # a Monday
WED = MON + timedelta(days=2)
SUN = MON + timedelta(days=6)


def row(day, *, status=S.COMPLETED, approval=A.NONE, grade=None, completed_at=None, bonus=False):
    return ChoreRow(assigned_date=day, status=status, completed_at=completed_at, grade=grade,
                    approval=approval, is_bonus=bonus)


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


class TestCatalogAndRotation:
    def test_catalog_is_the_spec_order_and_defaults(self):
        assert list(QUESTS.items()) == [("on_time", 3), ("extra_mile", 1), ("perfect_days", 2), ("go_getter", 1)]

    def test_week_monday(self):
        assert week_monday(WED) == MON and week_monday(MON) == MON and week_monday(SUN) == MON

    def test_rotation_is_a_cycle_of_the_four_keys(self):
        order = rotation(MON, UUID(int=0))
        assert sorted(order) == sorted(QUESTS) and len(order) == 4
        keys = list(QUESTS)
        start = keys.index(order[0])
        assert order == keys[start:] + keys[:start]

    def test_a_kid_moves_one_step_each_week(self):
        kid = UUID(int=7)
        assert rotation(MON + timedelta(days=7), kid)[0] == rotation(MON, kid)[1]

    def test_siblings_start_at_different_points(self):
        assert rotation(MON, UUID(int=0))[0] != rotation(MON, UUID(int=1))[0]


class TestSizeTarget:
    def test_no_history_gives_the_default(self):
        assert size_target(3, 0, 0, 10) == 3

    def test_stretches_ten_percent_above_the_four_week_average_rounded_up(self):
        assert size_target(3, 40, 0, 20) == 11      # avg 10 -> 11 exactly (no float creep to 12)
        assert size_target(3, 41, 0, 20) == 12      # avg 10.25 -> 11.275 -> 12

    def test_never_below_the_default(self):
        assert size_target(3, 4, 0, 10) == 3        # avg 1 -> 1.1 -> 2, default wins

    def test_capped_by_what_is_still_possible(self):
        assert size_target(3, 0, 1, 1) == 2

    def test_not_achievable_when_nothing_is_left(self):
        assert size_target(3, 0, 2, 0) is None

    def test_a_quest_never_starts_finished(self):
        assert size_target(3, 0, 5, 4) is None      # already past the stretch goal

    def test_not_offered(self):
        assert size_target(3, 0, 0, None) is None


class TestChoreState:
    def test_completed_on_time_without_review_counts(self):
        assert chore_state(row(WED), WED, UTC) == "yes"
        assert chore_state(row(WED, completed_at=at(WED, 23)), WED, UTC) == "yes"

    def test_approved_counts(self):
        assert chore_state(row(WED, approval=A.APPROVED), WED, UTC) == "yes"

    def test_awaiting_review_can_still_count(self):
        assert chore_state(row(WED, approval=A.PENDING), WED, UTC) == "maybe"

    def test_rejected_missed_or_late_never_counts(self):
        assert chore_state(row(WED, approval=A.REJECTED), WED, UTC) == "no"
        assert chore_state(row(WED, grade="missed"), WED, UTC) == "no"
        assert chore_state(row(MON, completed_at=at(WED)), WED, UTC) == "no"

    def test_family_timezone_decides_the_day(self):
        mx = ZoneInfo("America/Mexico_City")
        late_evening_local = datetime(2026, 9, 29, 4, 30, tzinfo=timezone.utc)   # Mon 22:30 in Mexico City
        assert chore_state(row(MON, completed_at=late_evening_local), WED, mx) == "yes"
        assert chore_state(row(MON, completed_at=late_evening_local), WED, UTC) == "no"

    def test_open_chore_today_or_later_can_still_count(self):
        assert chore_state(row(WED, status=S.PENDING), WED, UTC) == "maybe"
        assert chore_state(row(SUN, status=S.PENDING), WED, UTC) == "maybe"

    def test_open_chore_from_an_earlier_day_cannot(self):
        assert chore_state(row(MON, status=S.PENDING), WED, UTC) == "no"
        assert chore_state(row(MON, status=S.OVERDUE), WED, UTC) == "no"


class TestWeekStats:
    def test_counts_each_type(self):
        rows = [
            row(MON), row(MON),                                   # Monday: perfect
            row(MON + timedelta(days=1)), row(MON + timedelta(days=1), status=S.OVERDUE),   # Tuesday: failed
            row(WED, status=S.PENDING), row(WED, approval=A.PENDING),                         # Wednesday: open
            row(SUN, status=S.PENDING),                           # Sunday: open
            row(WED, status=S.CANCELLED),                         # waived: not a due chore
            row(WED, bonus=True, approval=A.APPROVED),            # bonus done
            row(WED, bonus=True, approval=A.PENDING),             # bonus awaiting review
        ]
        s = week_stats(rows, 2, WED, UTC)
        assert s.done == {"on_time": 3, "perfect_days": 1, "extra_mile": 1, "go_getter": 2}
        assert s.possible["on_time"] == 3          # Wed pending + Wed awaiting review + Sun pending
        assert s.possible["perfect_days"] == 2     # Wednesday and Sunday can still become perfect

    def test_a_day_with_nothing_due_is_neither_perfect_nor_open(self):
        s = week_stats([], 0, WED, UTC)
        assert s.done == {"on_time": 0, "perfect_days": 0, "extra_mile": 0, "go_getter": 0}
        assert s.possible["on_time"] == 0 and s.possible["perfect_days"] == 0

    def test_on_sunday_only_today_is_still_possible(self):
        rows = [row(MON, status=S.OVERDUE), row(SUN, status=S.PENDING)]
        s = week_stats(rows, 0, SUN, UTC)
        assert s.possible["on_time"] == 1 and s.possible["perfect_days"] == 1


class TestPickQuest:
    ORDER = ["on_time", "extra_mile", "perfect_days", "go_getter"]
    ALL = {"on_time": True, "extra_mile": True, "perfect_days": True, "go_getter": True}

    def stats(self, done=None, possible=None):
        zero = dict.fromkeys(QUESTS, 0)
        return WeekStats(done={**zero, **(done or {})}, possible={**zero, **(possible or {})})

    def test_first_achievable_type_in_order_wins(self):
        assert pick_quest(self.ORDER, self.stats(possible={"on_time": 6}), {}, self.ALL) == ("on_time", 3)

    def test_skips_a_type_that_cannot_be_achieved(self):
        # no chores left -> on_time impossible -> extra_mile (open-ended, default 1)
        assert pick_quest(self.ORDER, self.stats(), {}, self.ALL) == ("extra_mile", 1)

    def test_skips_a_type_that_is_not_offered(self):
        offered = {**self.ALL, "extra_mile": False, "go_getter": False}
        got = pick_quest(self.ORDER, self.stats(possible={"perfect_days": 4}), {}, offered)
        assert got == ("perfect_days", 2)

    def test_none_when_nothing_qualifies(self):
        offered = {"on_time": True, "perfect_days": True, "extra_mile": False, "go_getter": False}
        assert pick_quest(self.ORDER, self.stats(), {}, offered) is None

    def test_open_ended_goal_uses_history_and_is_capped(self):
        offered = {**self.ALL, "on_time": False}
        order = ["extra_mile", "on_time", "perfect_days", "go_getter"]
        assert pick_quest(order, self.stats(), {"extra_mile": 400}, offered) == ("extra_mile", OPEN_ENDED_CAP)
        # already at the cap -> nothing more to ask for -> the next offered type is used
        assert pick_quest(order, self.stats(done={"extra_mile": 7}), {}, offered) == ("go_getter", 1)

    def test_a_type_already_past_its_goal_is_skipped(self):
        # 2 gigs already approved, default goal 1 -> the goal is already met -> not this week's quest
        order = ["go_getter", "on_time", "extra_mile", "perfect_days"]
        assert pick_quest(order, self.stats(done={"go_getter": 2}), {}, self.ALL) == ("extra_mile", 1)
```

- [ ] **Step 2: Run — RED**

Run (from `backend/`, with the Global Constraints env): `… pytest -q --no-cov -p no:warnings tests/test_quest_rules.py </dev/null`
Expected: collection error — `ModuleNotFoundError: No module named 'app.services.quest_service'`.

- [ ] **Step 3: Implement** — create `backend/app/services/quest_service.py`:

```python
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
```

- [ ] **Step 4: Run — GREEN**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_rules.py </dev/null`
Expected: all pass. Then `/opt/homebrew/bin/ruff check app` → `All checks passed!`.

If `test_open_ended_goal_uses_history_and_is_capped` fails on its first assertion, check the arithmetic before touching code: history 400 → stretch `ceil(4400/40) = 110`, ceiling `0 + (7 − 0) = 7`, target 7.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/quest_service.py backend/tests/test_quest_rules.py
git commit -m "feat(ux-d3): pure weekly-quest rules — rotation, goal sizing, week stats"
```

---

### Task 2: `weekly_quests` table, family setting, export registry

**Files:**
- Create: `backend/app/models/weekly_quest.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/family.py`, `backend/app/schemas/family.py`
- Create: `backend/migrations/versions/2026_10_01_weekly_quests.py`
- Modify: `backend/app/services/family_export_service.py`, `backend/tests/test_family_delete_export.py`
- Test: `backend/tests/test_quest_model.py`

**Interfaces:**
- Produces (model): `WeeklyQuest` in `app/models/weekly_quest.py` — table `weekly_quests`: `id` UUID PK, `family_id` UUID FK NOT NULL (indexed), `user_id` UUID FK NOT NULL (indexed), `week_start` Date NOT NULL, `quest` String(32) NOT NULL, `target` Integer NOT NULL, `bonus_points` Integer NOT NULL, `created_at` timestamptz NOT NULL, `rewarded_at` timestamptz NULL, `seen_at` timestamptz NULL; unique constraint `uq_weekly_quests_family_user_week` on `(family_id, user_id, week_start)`; checks `ck_weekly_quests_target` (`target >= 1`) and `ck_weekly_quests_bonus` (`bonus_points >= 0`).
- Produces (setting): `Family.quest_bonus_points` (Integer NOT NULL, default 20); `FamilyUpdate.quest_bonus_points: Optional[int]` (`ge=0, le=500`); `FamilyResponse.quest_bonus_points: int = 20`. The existing `PATCH /api/families/me` (parent only) persists it with no route change.
- Produces (migration): revision `weekly_quests`, down revision `user_badges`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_quest_model.py`:

```python
"""UX-D3 weekly_quests table constraints + the family bonus setting."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.weekly_quest import WeeklyQuest

MON = date(2026, 9, 28)


def _quest(kid, *, week=MON, target=3, bonus=20):
    return WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest="on_time",
                       target=target, bonus_points=bonus, created_at=datetime.now(timezone.utc))


async def test_one_quest_per_kid_per_week(db_session, test_child_user):
    db_session.add(_quest(test_child_user))
    await db_session.commit()
    db_session.add(_quest(test_child_user))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_a_new_week_gets_a_new_quest(db_session, test_child_user):
    db_session.add_all([_quest(test_child_user), _quest(test_child_user, week=date(2026, 10, 5))])
    await db_session.commit()


async def test_target_must_be_at_least_one(db_session, test_child_user):
    db_session.add(_quest(test_child_user, target=0))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_new_quests_start_unpaid_and_unseen(db_session, test_child_user):
    q = _quest(test_child_user)
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)
    assert q.rewarded_at is None and q.seen_at is None and q.id is not None


class TestFamilySetting:
    async def test_default_is_twenty(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 20

    async def test_parent_can_change_it(self, client, auth_headers, db_session, test_family):
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 35}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["quest_bonus_points"] == 35
        await db_session.refresh(test_family)
        assert test_family.quest_bonus_points == 35

    async def test_zero_is_allowed_and_bounds_are_enforced(self, client, auth_headers, test_family):
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": 0}, headers=auth_headers)).status_code == 200
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": -1}, headers=auth_headers)).status_code == 422
        assert (await client.patch("/api/families/me", json={"quest_bonus_points": 501}, headers=auth_headers)).status_code == 422

    async def test_a_kid_cannot_change_it(self, client, test_child_user):
        login = await client.post("/api/auth/login", json={"email": "child@test.com", "password": "password123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.patch("/api/families/me", json={"quest_bonus_points": 500}, headers=h)
        assert r.status_code == 403
```

In `backend/tests/test_family_delete_export.py`, inside `test_export_zip_members_and_isolation`, add `"progress/quests.json",` to the expected member set, next to the existing `"progress/badges.json"` entry (if `progress/badges.json` is not in that set, add both lines after `"notifications.json",`).

- [ ] **Step 2: Run — RED**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_model.py </dev/null`
Expected: collection error — `ModuleNotFoundError: No module named 'app.models.weekly_quest'`.

- [ ] **Step 3: Model** — create `backend/app/models/weekly_quest.py`:

```python
"""UX-D3: one row per kid per week — which quest they have, its goal, the
bonus it pays, and whether it was paid / seen. Progress is derived on read."""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WeeklyQuest(Base):
    __tablename__ = "weekly_quests"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", "week_start", name="uq_weekly_quests_family_user_week"),
        CheckConstraint("target >= 1", name="ck_weekly_quests_target"),
        CheckConstraint("bonus_points >= 0", name="ck_weekly_quests_bonus"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start = Column(Date, nullable=False)          # the Monday (family timezone)
    quest = Column(String(32), nullable=False)         # catalog key, e.g. "on_time"
    target = Column(Integer, nullable=False)           # fixed at creation, never moves
    bonus_points = Column(Integer, nullable=False)     # family setting at creation
    created_at = Column(DateTime(timezone=True), nullable=False)
    rewarded_at = Column(DateTime(timezone=True), nullable=True)   # set when the bonus is paid
    seen_at = Column(DateTime(timezone=True), nullable=True)       # set when the kid saw the done moment

    def __repr__(self):
        return f"<WeeklyQuest(user_id={self.user_id}, week_start={self.week_start}, quest={self.quest})>"
```

Register it in `backend/app/models/__init__.py`: add `from app.models.weekly_quest import WeeklyQuest` directly after the `from app.models.user_badge import UserBadge` line, and add `"WeeklyQuest",` to `__all__` after `"UserBadge",` (follow whatever position `"UserBadge"` has there).

- [ ] **Step 4: Family setting**

`backend/app/models/family.py` — directly after the `point_value_cents = Column(...)` definition (it spans several lines; add after its closing parenthesis):

```python
    # UX-D3: points paid when a kid completes their weekly quest. 0 switches
    # weekly quests off for the family (no quest is created, nothing is paid).
    quest_bonus_points = Column(Integer, nullable=False, default=20, server_default="20")
```

`backend/app/schemas/family.py`:
- in `FamilyUpdate`, after the `point_value_cents` field:

```python
    # UX-D3 weekly quest bonus in points; 0 switches weekly quests off.
    quest_bonus_points: Optional[int] = Field(None, ge=0, le=500)
```

- in the response schema that already carries `point_value_cents: int = 100` (the family response model), add after it:

```python
    quest_bonus_points: int = 20
```

- [ ] **Step 5: Migration** — create `backend/migrations/versions/2026_10_01_weekly_quests.py`:

```python
"""weekly_quests + families.quest_bonus_points for UX-D3

Revision ID: weekly_quests
Revises: user_badges
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "weekly_quests"
down_revision = "user_badges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("quest_bonus_points", sa.Integer(), nullable=False, server_default="20"),
    )
    op.create_table(
        "weekly_quests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("quest", sa.String(32), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("bonus_points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("family_id", "user_id", "week_start", name="uq_weekly_quests_family_user_week"),
        sa.CheckConstraint("target >= 1", name="ck_weekly_quests_target"),
        sa.CheckConstraint("bonus_points >= 0", name="ck_weekly_quests_bonus"),
    )
    op.create_index("ix_weekly_quests_family_id", "weekly_quests", ["family_id"])
    op.create_index("ix_weekly_quests_user_id", "weekly_quests", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_weekly_quests_user_id", table_name="weekly_quests")
    op.drop_index("ix_weekly_quests_family_id", table_name="weekly_quests")
    op.drop_table("weekly_quests")
    op.drop_column("families", "quest_bonus_points")
```

- [ ] **Step 6: Family export** — in `backend/app/services/family_export_service.py`, mirror exactly what the file already does for `UserBadge` (search for `UserBadge` and `badges`):
- import `WeeklyQuest` where `UserBadge` is imported;
- add `WeeklyQuest,` to the `EXPORTED_FAMILY_TABLES` model tuple right after `UserBadge,`;
- fetch the rows right after the line `badges = await _rows(db, fam(UserBadge))`:

```python
        quests = await _rows(db, fam(WeeklyQuest))
```

- add the ZIP member right after `"progress/badges.json": _dump(badges),`:

```python
            "progress/quests.json": _dump(quests),
```

- [ ] **Step 7: Run — GREEN**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_model.py tests/test_family_delete_export.py </dev/null`
Expected: all pass (the export file includes `test_every_family_scoped_table_is_exported_or_excluded`, which would fail without Step 6).

- [ ] **Step 8: Verify the migration chain** (from `backend/`, same env exports; no pytest running):

Run: `/Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/alembic heads </dev/null 2>&1 | tail -1`
Expected: `weekly_quests (head)`.

Run: `/Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/alembic upgrade user_badges:weekly_quests --sql </dev/null 2>&1 | grep -n "quest_bonus_points\|uq_weekly_quests\|CREATE TABLE weekly_quests"`
Expected: three matching lines (the column, the constraint name, the table).

Then `/opt/homebrew/bin/ruff check app` → `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/weekly_quest.py backend/app/models/__init__.py backend/app/models/family.py backend/app/schemas/family.py backend/migrations/versions/2026_10_01_weekly_quests.py backend/app/services/family_export_service.py backend/tests/test_quest_model.py backend/tests/test_family_delete_export.py
git commit -m "feat(ux-d3): weekly_quests table + family quest bonus setting"
```

---

### Task 3: QuestService — create, derive progress, pay once, ack

**Files:**
- Modify: `backend/app/schemas/progress.py` (append quest schemas)
- Modify: `backend/app/services/quest_service.py` (add imports + `QuestService`)
- Test: `backend/tests/test_quest_service.py`

**Interfaces:**
- Consumes: Task 1 `QUESTS`, `HISTORY_WEEKS`, `ChoreRow`, `WeekStats`, `week_monday`, `rotation`, `week_stats`, `pick_quest`; Task 2 `WeeklyQuest`, `Family.quest_bonus_points`; existing `ProgressService.family_today(db, family_id) -> (date, ZoneInfo)`, `KID_ROLES`, `PointsService._get_user_locked(db, user_id, family_id) -> User` (row lock), `effective_modules(enabled) -> set[str]`.
- Produces (schemas, `app/schemas/progress.py`): `QuestProgress { id: UUID, quest: str, target: int, progress: int, bonus_points: int, week_start: date, days_left: int, completed: bool }`, `QuestCelebrate { id: UUID, quest: str, target: int, bonus_points: int, last_week: bool }`, `QuestResponse { applies: bool, gig_term: str = "gig", quest: QuestProgress | None, celebrate: QuestCelebrate | None }`, `AckQuestRequest { id: UUID }`.
- Produces (service): `QuestService.stats_for(db, family_id, user_id, week_start, tz, today) -> WeekStats`; `QuestService._history(db, family_id, user_id, week_start, tz, today) -> dict[str, int]`; `QuestService._offered(db, family_id, role, star_mode, enabled_modules) -> dict[str, bool]`; `QuestService._settle(db, quest: WeeklyQuest, lang: str) -> None`; `QuestService.sync(db, user) -> QuestResponse`; `QuestService.ack(db, user, quest_id: UUID) -> None`; `QuestService.hub_progress(db, family_id, kid_ids: list[UUID]) -> dict[UUID, tuple[int, int, bool]]` (progress, target, done).

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_quest_service.py`:

```python
"""UX-D3 weekly quest against the test DB: create, derive, pay once, ack.

Every date is built from the family's "today", so the suite passes on any
weekday (a quest's week is the family-local Monday–Sunday around today).
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update

from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.weekly_quest import WeeklyQuest
from app.services.progress_service import ProgressService
from app.services.quest_service import QuestService, rotation, week_monday


async def _ctx(db, kid):
    today, tz = await ProgressService.family_today(db, kid.family_id)
    return today, tz, week_monday(today)


async def _template(db, family_id, *, bonus=False, active=True):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=active,
                     family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, *, status=AssignmentStatus.COMPLETED, grade=None,
                  approval=ApprovalStatus.NONE, family_id=None):
    a = TaskAssignment(family_id=family_id or kid.family_id, template_id=template.id, assigned_to=kid.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _quest(db, kid, week, quest, target, *, bonus=20):
    q = WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest=quest, target=target,
                    bonus_points=bonus, created_at=datetime.now(timezone.utc))
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def _bonus_rows(db, kid):
    return list((await db.execute(
        select(PointTransaction).where(PointTransaction.user_id == kid.id, PointTransaction.type == PT.BONUS)
    )).scalars().all())


async def _quest_count(db, kid):
    return (await db.execute(
        select(func.count()).select_from(WeeklyQuest).where(WeeklyQuest.user_id == kid.id)
    )).scalar()


async def _gigs_off(db, family):
    family.enabled_modules = ["chat"]
    await db.commit()


class TestCreation:
    async def test_creates_one_quest_for_the_week_from_the_rotation(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        for _ in range(3):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        resp = await QuestService.sync(db_session, kid)
        expected = next(k for k in rotation(week, kid.id) if k in ("on_time", "perfect_days"))
        assert resp.applies is True and resp.quest is not None
        assert resp.quest.quest == expected
        assert resp.quest.target == (3 if expected == "on_time" else 1)
        assert resp.quest.progress == 0 and resp.quest.completed is False
        assert resp.quest.bonus_points == 20 and resp.quest.week_start == week
        assert resp.quest.days_left == 7 - today.weekday()
        assert resp.celebrate is None
        again = await QuestService.sync(db_session, kid)
        assert again.quest.id == resp.quest.id and await _quest_count(db_session, kid) == 1

    async def test_no_quest_until_something_qualifies_then_it_is_created(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        first = await QuestService.sync(db_session, kid)          # Monday 6 am: nothing assigned yet
        assert first.applies is True and first.quest is None and first.celebrate is None
        assert await _quest_count(db_session, kid) == 0
        today, _tz, _week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        later = await QuestService.sync(db_session, kid)
        assert later.quest is not None and await _quest_count(db_session, kid) == 1

    async def test_the_goal_does_not_move_when_chores_are_added(self, db_session, test_family, test_child_user):
        kid = test_child_user
        await _gigs_off(db_session, test_family)
        today, _tz, _week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        for _ in range(3):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        before = (await QuestService.sync(db_session, kid)).quest
        for _ in range(5):
            await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        after = (await QuestService.sync(db_session, kid)).quest
        assert (after.id, after.quest, after.target) == (before.id, before.quest, before.target)

    async def test_bonus_zero_switches_quests_off(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, _week = await _ctx(db_session, kid)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today,
                      status=AssignmentStatus.PENDING)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.applies is False and resp.quest is None
        assert await _quest_count(db_session, kid) == 0

    async def test_parent_does_not_apply(self, db_session, test_parent_user):
        resp = await QuestService.sync(db_session, test_parent_user)
        assert resp.applies is False and resp.quest is None and resp.celebrate is None

    async def test_history_counts_the_previous_four_weeks_only(self, db_session, test_child_user):
        kid = test_child_user
        today, tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        last_week = week - timedelta(days=7)
        for i in range(5):
            await _assign(db_session, kid, chore, last_week + timedelta(days=i))
        await _assign(db_session, kid, chore, last_week + timedelta(days=5), status=AssignmentStatus.OVERDUE)
        for i in range(3):
            await _assign(db_session, kid, chore, week - timedelta(days=42 + i))     # six weeks back
        await _assign(db_session, kid, chore, today)                                  # this week: not history
        history = await QuestService._history(db_session, kid.family_id, kid.id, week, tz, today)
        assert history["on_time"] == 5 and history["perfect_days"] == 5

    async def test_offered_types(self, db_session, test_family, test_child_user, test_teen_user):
        fid = test_family.id
        off = await QuestService._offered(db_session, fid, test_child_user.role, False, None)
        assert off == {"on_time": True, "perfect_days": True, "extra_mile": False, "go_getter": False}
        await _template(db_session, fid, bonus=True, active=False)
        assert (await QuestService._offered(db_session, fid, test_child_user.role, False, None))["extra_mile"] is False
        await _template(db_session, fid, bonus=True)
        assert (await QuestService._offered(db_session, fid, test_child_user.role, False, None))["extra_mile"] is True
        db_session.add(GigOffering(family_id=fid, title="Teens only", points=50, allowed_roles=["teen"]))
        await db_session.commit()
        assert (await QuestService._offered(db_session, fid, test_child_user.role, False, None))["go_getter"] is False
        assert (await QuestService._offered(db_session, fid, test_teen_user.role, False, None))["go_getter"] is True
        db_session.add(GigOffering(family_id=fid, title="Anyone", points=20))
        await db_session.commit()
        assert (await QuestService._offered(db_session, fid, test_child_user.role, False, None))["go_getter"] is True
        # star-mode kids have no gig board; a family with gigs off has none either
        assert (await QuestService._offered(db_session, fid, test_child_user.role, True, None))["go_getter"] is False
        assert (await QuestService._offered(db_session, fid, test_child_user.role, False, ["chat"]))["go_getter"] is False


class TestProgressAndPayment:
    async def test_on_time_counts_strictly_and_pays_when_the_goal_is_reached(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        quest = await _quest(db_session, kid, week, "on_time", 2)
        await _assign(db_session, kid, chore, today)                                           # counts
        waiting = await _assign(db_session, kid, chore, today, approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, chore, today, approval=ApprovalStatus.REJECTED)
        await _assign(db_session, kid, chore, today, grade="missed")
        points_before = kid.points
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.id == quest.id and resp.quest.progress == 1 and resp.quest.completed is False
        assert resp.celebrate is None and await _bonus_rows(db_session, kid) == []
        await db_session.execute(                                                              # the parent approves
            update(TaskAssignment).where(TaskAssignment.id == waiting.id).values(approval_status=ApprovalStatus.APPROVED)
        )
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 2 and resp.quest.completed is True
        assert resp.celebrate is not None and resp.celebrate.id == quest.id and resp.celebrate.last_week is False
        assert resp.celebrate.bonus_points == 20
        rows = await _bonus_rows(db_session, kid)
        assert len(rows) == 1 and rows[0].points == 20 and rows[0].family_id == kid.family_id
        assert rows[0].balance_before == points_before and rows[0].balance_after == points_before + 20
        await db_session.refresh(kid)
        assert kid.points == points_before + 20

    async def test_the_bonus_is_paid_once_across_many_reads(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        points_before = kid.points
        for _ in range(3):
            resp = await QuestService.sync(db_session, kid)
        assert resp.quest.completed is True and resp.quest.progress == 1
        assert len(await _bonus_rows(db_session, kid)) == 1
        await db_session.refresh(kid)
        assert kid.points == points_before + 20

    async def test_settle_twice_pays_once(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        quest = await _quest(db_session, kid, week, "on_time", 1)
        await QuestService._settle(db_session, quest, "en")
        await QuestService._settle(db_session, quest, "en")
        assert len(await _bonus_rows(db_session, kid)) == 1 and quest.rewarded_at is not None

    async def test_the_bonus_is_the_amount_fixed_at_creation(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "on_time", 1, bonus=20)
        test_family.quest_bonus_points = 50
        await db_session.commit()
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        await QuestService.sync(db_session, kid)
        assert [r.points for r in await _bonus_rows(db_session, kid)] == [20]

    async def test_bonus_zero_stops_an_in_flight_quest(self, db_session, test_family, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        quest = await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.applies is False
        await db_session.refresh(quest)
        assert quest.rewarded_at is None and await _bonus_rows(db_session, kid) == []

    async def test_last_weeks_quest_is_paid_on_this_weeks_read(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        last_week = week - timedelta(days=7)
        older_week = week - timedelta(days=14)
        last = await _quest(db_session, kid, last_week, "on_time", 1)
        older = await _quest(db_session, kid, older_week, "on_time", 1)
        await _assign(db_session, kid, chore, last_week)       # Sunday-night finish / late approval
        await _assign(db_session, kid, chore, older_week)
        resp = await QuestService.sync(db_session, kid)
        assert resp.celebrate is not None and resp.celebrate.id == last.id and resp.celebrate.last_week is True
        assert len(await _bonus_rows(db_session, kid)) == 1
        await db_session.refresh(older)
        assert older.rewarded_at is None                       # two weeks back is never settled

    async def test_extra_mile_counts_bonus_tasks_that_count(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        await _quest(db_session, kid, week, "extra_mile", 2)
        await _assign(db_session, kid, bonus, today, approval=ApprovalStatus.APPROVED)
        await _assign(db_session, kid, bonus, today, approval=ApprovalStatus.PENDING)
        await _assign(db_session, kid, await _template(db_session, kid.family_id), today)   # a chore, not a bonus
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.quest == "extra_mile" and resp.quest.progress == 1

    async def test_go_getter_counts_gigs_approved_this_week(self, db_session, test_child_user):
        kid = test_child_user
        _today, _tz, week = await _ctx(db_session, kid)
        await _quest(db_session, kid, week, "go_getter", 2)
        gigs = [GigOffering(family_id=kid.family_id, title=f"Gig {i}", points=30) for i in range(3)]
        db_session.add_all(gigs)
        await db_session.commit()
        now = datetime.now(timezone.utc)
        db_session.add_all([
            GigClaim(gig_id=gigs[0].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.APPROVED, approved_at=now),
            GigClaim(gig_id=gigs[1].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.APPROVED, approved_at=now - timedelta(days=8)),
            GigClaim(gig_id=gigs[2].id, family_id=kid.family_id, claimed_by=kid.id,
                     status=GigClaimStatus.COMPLETED),
        ])
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.quest == "go_getter" and resp.quest.progress == 1

    async def test_perfect_days_needs_every_chore_of_the_day(self, db_session, test_child_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _quest(db_session, kid, week, "perfect_days", 1)
        await _assign(db_session, kid, chore, today)
        open_one = await _assign(db_session, kid, chore, today, status=AssignmentStatus.PENDING)
        assert (await QuestService.sync(db_session, kid)).quest.progress == 0
        await db_session.execute(
            update(TaskAssignment).where(TaskAssignment.id == open_one.id).values(status=AssignmentStatus.COMPLETED)
        )
        await db_session.commit()
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 1 and resp.quest.completed is True

    async def test_a_siblings_and_another_familys_work_never_counts(self, db_session, test_child_user, test_teen_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        bonus = await _template(db_session, kid.family_id, bonus=True)
        await _quest(db_session, kid, week, "on_time", 1)
        await _assign(db_session, test_teen_user, chore, today)                       # sibling's chore
        await _assign(db_session, test_teen_user, bonus, today, approval=ApprovalStatus.APPROVED)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        await _assign(db_session, kid, await _template(db_session, other.id), today, family_id=other.id)
        resp = await QuestService.sync(db_session, kid)
        assert resp.quest.progress == 0 and resp.quest.completed is False
        stats = await QuestService.stats_for(db_session, kid.family_id, kid.id, week, _tz, today)
        assert stats.done == {"on_time": 0, "perfect_days": 0, "extra_mile": 0, "go_getter": 0}
        assert await _bonus_rows(db_session, kid) == []


class TestAckAndHub:
    async def _paid(self, db, kid):
        today, _tz, week = await _ctx(db, kid)
        quest = await _quest(db, kid, week, "on_time", 1)
        await _assign(db, kid, await _template(db, kid.family_id), today)
        await QuestService.sync(db, kid)
        return quest

    async def test_ack_marks_the_done_moment_seen(self, db_session, test_child_user):
        quest = await self._paid(db_session, test_child_user)
        assert (await QuestService.sync(db_session, test_child_user)).celebrate.id == quest.id
        await QuestService.ack(db_session, test_child_user, quest.id)
        resp = await QuestService.sync(db_session, test_child_user)
        assert resp.celebrate is None and resp.quest.completed is True and resp.quest.progress == resp.quest.target

    async def test_ack_ignores_someone_elses_quest(self, db_session, test_child_user, test_teen_user):
        quest = await self._paid(db_session, test_child_user)
        await QuestService.ack(db_session, test_teen_user, quest.id)
        assert (await QuestService.sync(db_session, test_child_user)).celebrate is not None

    async def test_hub_progress_reads_without_creating_or_paying(self, db_session, test_family,
                                                                 test_child_user, test_teen_user):
        kid = test_child_user
        today, _tz, week = await _ctx(db_session, kid)
        chore = await _template(db_session, kid.family_id)
        await _quest(db_session, kid, week, "on_time", 2)
        await _assign(db_session, kid, chore, today)
        await _assign(db_session, test_teen_user, chore, today, status=AssignmentStatus.PENDING)   # teen has no quest row
        ids = [kid.id, test_teen_user.id]
        hub = await QuestService.hub_progress(db_session, test_family.id, ids)
        assert hub == {kid.id: (1, 2, False)}
        assert await _quest_count(db_session, test_teen_user) == 0
        await _assign(db_session, kid, chore, today)                    # goal reached, but the hub never pays
        hub = await QuestService.hub_progress(db_session, test_family.id, ids)
        assert hub == {kid.id: (2, 2, False)} and await _bonus_rows(db_session, kid) == []
        test_family.quest_bonus_points = 0
        await db_session.commit()
        assert await QuestService.hub_progress(db_session, test_family.id, ids) == {}
```

- [ ] **Step 2: Run — RED**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_service.py </dev/null`
Expected: every test FAILS with `ImportError: cannot import name 'QuestService' from 'app.services.quest_service'`.

- [ ] **Step 3: Add the schemas** — append to `backend/app/schemas/progress.py` (it already imports `date`, `datetime`, `Optional`, `UUID`, `BaseModel`, `Field`); also extend the module docstring to mention UX-D3:

```python
class QuestProgress(BaseModel):
    id: UUID
    quest: str                 # catalog key
    target: int
    progress: int              # capped at target; equals target once paid
    bonus_points: int
    week_start: date
    days_left: int             # counts today (Sunday = 1)
    completed: bool            # the bonus was paid


class QuestCelebrate(BaseModel):
    id: UUID
    quest: str
    target: int
    bonus_points: int
    last_week: bool


class QuestResponse(BaseModel):
    applies: bool
    gig_term: str = "gig"      # the family's word for a gig (go_getter copy)
    quest: Optional[QuestProgress] = None
    celebrate: Optional[QuestCelebrate] = None


class AckQuestRequest(BaseModel):
    id: UUID
```

- [ ] **Step 4: Implement the service** — in `backend/app/services/quest_service.py`:

Replace the import block at the top (keep the module docstring) with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import effective_modules
from app.models.family import Family
from app.models.gig import GigClaim, GigClaimStatus, GigOffering, GigOfferingStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.user import User, UserRole
from app.models.weekly_quest import WeeklyQuest
from app.schemas.progress import QuestCelebrate, QuestProgress, QuestResponse
from app.services.points_service import PointsService
from app.services.progress_service import KID_ROLES, ProgressService
```

Append below `pick_quest`:

```python
# ── Queries (family-scoped) ──────────────────────────────────────────────
class QuestService:
    @staticmethod
    async def _chore_rows(
        db: AsyncSession, family_id: UUID, user_id: UUID, start: date, end: date,
    ) -> list[ChoreRow]:
        """The kid's assignments dated in [start, end)."""
        rows = (await db.execute(
            select(
                TaskAssignment.assigned_date,
                TaskAssignment.status,
                TaskAssignment.completed_at,
                TaskAssignment.completion_grade,
                TaskAssignment.approval_status,
                TaskTemplate.is_bonus,
            )
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.assigned_date >= start,
                TaskAssignment.assigned_date < end,
            )
        )).all()
        return [
            ChoreRow(r.assigned_date, r.status, r.completed_at, r.completion_grade, r.approval_status, bool(r.is_bonus))
            for r in rows
        ]

    @staticmethod
    async def _gigs_approved(
        db: AsyncSession, family_id: UUID, user_id: UUID, start: date, end: date, tz: ZoneInfo,
    ) -> int:
        """Gig claims approved inside [start, end), family-local days."""
        lo = datetime.combine(start, time.min, tzinfo=tz)
        hi = datetime.combine(end, time.min, tzinfo=tz)
        return int((await db.execute(
            select(func.count()).select_from(GigClaim).where(
                GigClaim.family_id == family_id,
                GigClaim.claimed_by == user_id,
                GigClaim.status == GigClaimStatus.APPROVED,
                GigClaim.approved_at >= lo,
                GigClaim.approved_at < hi,
            )
        )).scalar() or 0)

    @staticmethod
    async def stats_for(
        db: AsyncSession, family_id: UUID, user_id: UUID, week_start: date, tz: ZoneInfo, today: date,
    ) -> WeekStats:
        end = week_start + timedelta(days=7)
        return week_stats(
            await QuestService._chore_rows(db, family_id, user_id, week_start, end),
            await QuestService._gigs_approved(db, family_id, user_id, week_start, end, tz),
            today, tz,
        )

    @staticmethod
    async def _history(
        db: AsyncSession, family_id: UUID, user_id: UUID, week_start: date, tz: ZoneInfo, today: date,
    ) -> dict[str, int]:
        """Per-type totals over the HISTORY_WEEKS full weeks before week_start."""
        start = week_start - timedelta(weeks=HISTORY_WEEKS)
        return week_stats(
            await QuestService._chore_rows(db, family_id, user_id, start, week_start),
            await QuestService._gigs_approved(db, family_id, user_id, start, week_start, tz),
            today, tz,
        ).done

    @staticmethod
    async def _offered(
        db: AsyncSession, family_id: UUID, role: UserRole, star_mode: bool,
        enabled_modules: Optional[Iterable[str]],
    ) -> dict[str, bool]:
        """Which quest types this kid can be given at all this week. The chore
        types are always offered — whether one is achievable is size_target's call."""
        has_bonus = (await db.execute(
            select(TaskTemplate.id).where(
                TaskTemplate.family_id == family_id,
                TaskTemplate.is_bonus.is_(True),
                TaskTemplate.is_active.is_(True),
            ).limit(1)
        )).first() is not None
        gig_open = False
        # Star-mode kids have no gig board; neither does a family with gigs off.
        if not star_mode and "gigs" in effective_modules(enabled_modules):
            role_name = role.value if hasattr(role, "value") else str(role)
            offerings = (await db.execute(
                select(GigOffering.allowed_roles).where(
                    GigOffering.family_id == family_id,
                    GigOffering.is_active.is_(True),
                    GigOffering.status == GigOfferingStatus.APPROVED.value,
                )
            )).all()
            gig_open = any(
                not allowed or role_name in {str(r).lower() for r in allowed}
                for (allowed,) in offerings
            )
        return {"on_time": True, "perfect_days": True, "extra_mile": has_bonus, "go_getter": gig_open}

    @staticmethod
    async def _rows(
        db: AsyncSession, family_id: UUID, user_id: UUID, weeks: list[date],
    ) -> dict[date, WeeklyQuest]:
        rows = (await db.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.family_id == family_id,
                WeeklyQuest.user_id == user_id,
                WeeklyQuest.week_start.in_(weeks),
            )
        )).scalars().all()
        return {q.week_start: q for q in rows}

    @staticmethod
    async def _settle(db: AsyncSession, quest: WeeklyQuest, lang: str) -> None:
        """Pay the bonus exactly once. The guarded UPDATE is the gate: of two
        requests settling the same quest, the second waits on the row lock and
        then matches nothing, so only one of them writes the transaction. The
        paid mark and the points are committed together."""
        paid = (await db.execute(
            update(WeeklyQuest)
            .where(WeeklyQuest.id == quest.id, WeeklyQuest.rewarded_at.is_(None))
            .values(rewarded_at=datetime.now(timezone.utc))
            .returning(WeeklyQuest.id)
            .execution_options(synchronize_session=False)   # the row is refreshed after the commit
        )).first()
        bonus = int(quest.bonus_points or 0)
        if paid is not None and bonus > 0:
            kid = await PointsService._get_user_locked(db, quest.user_id, quest.family_id)
            before = int(kid.points or 0)
            kid.points = before + bonus
            db.add(PointTransaction(
                type=TransactionType.BONUS,
                user_id=kid.id,
                family_id=kid.family_id,
                points=bonus,
                balance_before=before,
                balance_after=kid.points,
                description="Misión semanal lograda" if lang == "es" else "Weekly quest completed",
            ))
        await db.commit()
        await db.refresh(quest)

    @staticmethod
    def _response(
        current: Optional[WeeklyQuest], previous: Optional[WeeklyQuest], stats: WeekStats,
        today: date, gig_term: str,
    ) -> QuestResponse:
        quest = None
        if current is not None:
            target = int(current.target)
            paid = current.rewarded_at is not None
            quest = QuestProgress(
                id=current.id,
                quest=current.quest,
                target=target,
                # Once paid the bar stays full even if a later correction lowers the count.
                progress=target if paid else min(int(stats.done.get(current.quest, 0)), target),
                bonus_points=int(current.bonus_points),
                week_start=current.week_start,
                days_left=7 - today.weekday(),
                completed=paid,
            )
        celebrate = None
        for q, last_week in ((previous, True), (current, False)):     # last week's result first
            if q is not None and q.rewarded_at is not None and q.seen_at is None:
                celebrate = QuestCelebrate(
                    id=q.id, quest=q.quest, target=int(q.target),
                    bonus_points=int(q.bonus_points), last_week=last_week,
                )
                break
        return QuestResponse(applies=True, gig_term=gig_term, quest=quest, celebrate=celebrate)

    @staticmethod
    async def sync(db: AsyncSession, user: User) -> QuestResponse:
        """This week's quest for the kid: create it if missing (and something
        qualifies), pay the bonus if the goal is reached — for this week's
        quest and last week's — and return progress + any unseen result.
        This is a read endpoint that writes; both writes are idempotent."""
        if user.role not in KID_ROLES:
            return QuestResponse(applies=False)
        family_id, user_id, role = user.family_id, user.id, user.role
        star_mode = bool(user.star_mode)
        lang = "es" if (user.preferred_lang or "es").lower().startswith("es") else "en"
        fam = (await db.execute(
            select(Family.quest_bonus_points, Family.enabled_modules, Family.gig_term)
            .where(Family.id == family_id)
        )).first()
        bonus = int(fam.quest_bonus_points or 0) if fam else 0
        if bonus <= 0:
            return QuestResponse(applies=False)

        today, tz = await ProgressService.family_today(db, family_id)
        week_start = week_monday(today)
        last_week = week_start - timedelta(days=7)
        rows = await QuestService._rows(db, family_id, user_id, [week_start, last_week])
        stats = await QuestService.stats_for(db, family_id, user_id, week_start, tz, today)

        current = rows.get(week_start)
        if current is None:
            picked = pick_quest(
                rotation(week_start, user_id),
                stats,
                await QuestService._history(db, family_id, user_id, week_start, tz, today),
                await QuestService._offered(db, family_id, role, star_mode, fam.enabled_modules),
            )
            if picked is not None:
                key, target = picked
                await db.execute(
                    pg_insert(WeeklyQuest)
                    .values(
                        id=uuid4(), family_id=family_id, user_id=user_id, week_start=week_start,
                        quest=key, target=target, bonus_points=bonus,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(constraint="uq_weekly_quests_family_user_week")
                )
                await db.commit()
                current = (await QuestService._rows(db, family_id, user_id, [week_start])).get(week_start)

        if (
            current is not None and current.rewarded_at is None
            and stats.done.get(current.quest, 0) >= current.target
        ):
            await QuestService._settle(db, current, lang)

        previous = rows.get(last_week)
        if previous is not None and previous.rewarded_at is None:
            before = await QuestService.stats_for(db, family_id, user_id, last_week, tz, today)
            if before.done.get(previous.quest, 0) >= previous.target:
                await QuestService._settle(db, previous, lang)

        return QuestService._response(current, previous, stats, today, str(fam.gig_term or "gig"))

    @staticmethod
    async def ack(db: AsyncSession, user: User, quest_id: UUID) -> None:
        """Mark a paid quest's done moment as seen. Scoped to the caller's own
        rows; anyone else's id is ignored without an error."""
        await db.execute(
            update(WeeklyQuest)
            .where(
                WeeklyQuest.id == quest_id,
                WeeklyQuest.user_id == user.id,
                WeeklyQuest.family_id == user.family_id,
                WeeklyQuest.rewarded_at.is_not(None),
                WeeklyQuest.seen_at.is_(None),
            )
            .values(seen_at=datetime.now(timezone.utc))
        )
        await db.commit()

    @staticmethod
    async def hub_progress(
        db: AsyncSession, family_id: UUID, kid_ids: list[UUID],
    ) -> dict[UUID, tuple[int, int, bool]]:
        """(progress, target, done) per kid who has a quest this week, for the
        parent hub. Read-only: it never creates a quest and never pays."""
        bonus = (await db.execute(select(Family.quest_bonus_points).where(Family.id == family_id))).scalar()
        if not kid_ids or int(bonus or 0) <= 0:
            return {}
        today, tz = await ProgressService.family_today(db, family_id)
        week_start = week_monday(today)
        quests = (await db.execute(
            select(WeeklyQuest).where(
                WeeklyQuest.family_id == family_id,
                WeeklyQuest.week_start == week_start,
                WeeklyQuest.user_id.in_(kid_ids),
            )
        )).scalars().all()
        out: dict[UUID, tuple[int, int, bool]] = {}
        for q in quests:
            target = int(q.target)
            if q.rewarded_at is not None:
                out[q.user_id] = (target, target, True)
                continue
            stats = await QuestService.stats_for(db, family_id, q.user_id, week_start, tz, today)
            out[q.user_id] = (min(int(stats.done.get(q.quest, 0)), target), target, False)
        return out
```

- [ ] **Step 5: Run — GREEN**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_service.py tests/test_quest_rules.py tests/test_quest_model.py </dev/null`
Expected: all pass. Then `/opt/homebrew/bin/ruff check app` → `All checks passed!` (remove any import the linter reports as unused).

If a test fails after implementing the code exactly as written, find out why before changing anything, and say which one and why in your report. In particular `test_creates_one_quest_for_the_week_from_the_rotation` depends on the day it runs only through `days_left`; the type it expects comes from `rotation(...)`, so it must pass for any kid id and any weekday.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/quest_service.py backend/app/schemas/progress.py backend/tests/test_quest_service.py
git commit -m "feat(ux-d3): QuestService — create the week's quest, derive progress, pay once"
```

---

### Task 4: API endpoints + parent hub fields

**Files:**
- Modify: `backend/app/api/routes/progress.py`
- Modify: `backend/app/schemas/oversight.py` (`KidSummary`)
- Modify: `backend/app/services/oversight_service.py` (`get_summary`)
- Modify: `CLAUDE.md` (Progress row)
- Test: `backend/tests/test_quest_api.py`

**Interfaces:**
- Consumes: Task 3 `QuestService.sync(db, user) -> QuestResponse`, `QuestService.ack(db, user, quest_id)`, `QuestService.hub_progress(db, family_id, kid_ids) -> dict[UUID, tuple[int, int, bool]]`, schemas `QuestResponse`, `AckQuestRequest`.
- Produces: `GET /api/progress/quest` → `{ applies, gig_term, quest: { id, quest, target, progress, bonus_points, week_start, days_left, completed } | null, celebrate: { id, quest, target, bonus_points, last_week } | null }`; `POST /api/progress/quest/ack` with body `{ "id": "<uuid>" }` → 204 (404 for non-kids, 422 for a malformed id); `KidSummary.quest_progress: int | None`, `KidSummary.quest_target: int | None`, `KidSummary.quest_done: bool`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_quest_api.py`:

```python
"""UX-D3 weekly quest endpoints + parent hub fields."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.weekly_quest import WeeklyQuest
from app.services.oversight_service import OversightService
from app.services.progress_service import ProgressService
from app.services.quest_service import week_monday


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_quest(db, kid, *, target=1, done=1):
    """A quest for this week plus `done` completed chores dated today."""
    today, _tz = await ProgressService.family_today(db, kid.family_id)
    week = week_monday(today)
    template = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1,
                            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=kid.family_id)
    quest = WeeklyQuest(family_id=kid.family_id, user_id=kid.id, week_start=week, quest="on_time",
                        target=target, bonus_points=20, created_at=datetime.now(timezone.utc))
    db.add_all([template, quest])
    await db.commit()
    for _ in range(done):
        db.add(TaskAssignment(family_id=kid.family_id, template_id=template.id, assigned_to=kid.id,
                              status=AssignmentStatus.COMPLETED, approval_status=ApprovalStatus.NONE,
                              assigned_date=today, week_of=today - timedelta(days=today.weekday())))
    await db.commit()
    await db.refresh(quest)
    return quest


class TestGetQuest:
    async def test_child_without_work_gets_no_quest(self, client, test_child_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "child@test.com"))
        assert r.status_code == 200
        assert r.json() == {"applies": True, "gig_term": "gig", "quest": None, "celebrate": None}

    async def test_child_gets_the_quest_shape(self, client, db_session, test_child_user):
        quest = await _seed_quest(db_session, test_child_user, target=3, done=1)
        body = (await client.get("/api/progress/quest", headers=await _login(client, "child@test.com"))).json()
        assert body["applies"] is True and body["celebrate"] is None
        assert set(body["quest"]) == {"id", "quest", "target", "progress", "bonus_points", "week_start",
                                      "days_left", "completed"}
        assert body["quest"]["id"] == str(quest.id)
        assert (body["quest"]["quest"], body["quest"]["target"], body["quest"]["progress"]) == ("on_time", 3, 1)
        assert body["quest"]["completed"] is False and 1 <= body["quest"]["days_left"] <= 7

    async def test_teen_applies(self, client, test_teen_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json()["applies"] is True

    async def test_parent_does_not_apply(self, client, test_parent_user):
        r = await client.get("/api/progress/quest", headers=await _login(client, "parent@test.com"))
        assert r.status_code == 200
        assert r.json() == {"applies": False, "gig_term": "gig", "quest": None, "celebrate": None}

    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/quest")).status_code in (401, 403)


class TestAck:
    async def test_reaching_the_goal_pays_and_ack_clears_the_moment(self, client, db_session, test_child_user):
        quest = await _seed_quest(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        body = (await client.get("/api/progress/quest", headers=h)).json()
        assert body["quest"]["completed"] is True
        assert body["celebrate"] == {"id": str(quest.id), "quest": "on_time", "target": 1,
                                     "bonus_points": 20, "last_week": False}
        assert (await client.post("/api/progress/quest/ack", json={"id": str(quest.id)}, headers=h)).status_code == 204
        after = (await client.get("/api/progress/quest", headers=h)).json()
        assert after["celebrate"] is None and after["quest"]["completed"] is True

    async def test_ack_bounds_and_parent(self, client, test_child_user, test_parent_user):
        h = await _login(client, "child@test.com")
        assert (await client.post("/api/progress/quest/ack", json={"id": "nope"}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/quest/ack", json={}, headers=h)).status_code == 422
        assert (await client.post("/api/progress/quest/ack", json={"id": str(uuid4())}, headers=h)).status_code == 204
        hp = await _login(client, "parent@test.com")
        r = await client.post("/api/progress/quest/ack", json={"id": str(uuid4())}, headers=hp)
        assert r.status_code == 404


class TestKidSummary:
    async def test_quest_fields_per_kid(self, db_session, test_family, test_child_user, test_teen_user):
        await _seed_quest(db_session, test_child_user, target=3, done=1)
        summary = await OversightService.get_summary(db_session, test_family.id)
        by_id = {m.user_id: m for m in summary.members}
        child, teen = by_id[test_child_user.id], by_id[test_teen_user.id]
        assert (child.quest_progress, child.quest_target, child.quest_done) == (1, 3, False)
        assert (teen.quest_progress, teen.quest_target, teen.quest_done) == (None, None, False)
        assert isinstance(child.quest_progress, int)

    async def test_quest_fields_are_empty_when_quests_are_off(self, db_session, test_family, test_child_user):
        await _seed_quest(db_session, test_child_user, target=3, done=1)
        test_family.quest_bonus_points = 0
        await db_session.commit()
        summary = await OversightService.get_summary(db_session, test_family.id)
        kid = summary.members[0]
        assert (kid.quest_progress, kid.quest_target, kid.quest_done) == (None, None, False)
```

- [ ] **Step 2: Run — RED**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_api.py </dev/null`
Expected: FAIL — `GET /api/progress/quest` returns 404, and `KidSummary` has no `quest_progress`.

- [ ] **Step 3: Add the routes** — in `backend/app/api/routes/progress.py`:

Update the docstring to `"""UX-D1 progress (streak + rank, rank-up ack), UX-D2 badges and UX-D3 weekly quest for the signed-in kid."""`, add `AckQuestRequest` and `QuestResponse` to the existing `from app.schemas.progress import …` line (keep it alphabetical), add `from app.services.quest_service import QuestService` after the `progress_service` import, and append:

```python
@router.get("/quest", response_model=QuestResponse)
async def my_quest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuestResponse:
    """The signed-in kid's weekly quest. This GET also creates the week's
    quest and pays the bonus once the goal is reached (both idempotent) —
    like badges, the work happens on read instead of in hooks elsewhere."""
    return await QuestService.sync(db, current_user)


@router.post("/quest/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_quest(
    data: AckQuestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    await QuestService.ack(db, current_user, data.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Add the hub fields**

`backend/app/schemas/oversight.py` — in `KidSummary`, after `badge_count: int = 0`, add:

```python
    # UX-D3: this week's quest, when the kid has one (stored row + derived
    # progress). The hub only reads — it never creates or pays a quest.
    quest_progress: Optional[int] = None
    quest_target: Optional[int] = None
    quest_done: bool = False
```

`backend/app/services/oversight_service.py`:
- add `from app.services.quest_service import QuestService` next to the other service imports (keep the block's ordering);
- in `get_summary`, directly after the existing `badge_counts = await BadgeService.earned_counts(...)` statement, add:

```python
        quest_rows = await QuestService.hub_progress(db, family_id, [kid.id for kid in kids])
```

- inside the loop, directly before `members.append(`, add:

```python
            quest = quest_rows.get(kid.id)
```

- in the `KidSummary(...)` call, after the existing `badge_count=int(badge_counts.get(kid.id, 0)),` argument, add:

```python
                    quest_progress=int(quest[0]) if quest else None,
                    quest_target=int(quest[1]) if quest else None,
                    quest_done=bool(quest[2]) if quest else False,
```

- [ ] **Step 5: Run — GREEN**

Run: `… pytest -q --no-cov -p no:warnings tests/test_quest_api.py tests/test_quest_service.py tests/test_badge_api.py tests/test_progress_api.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py </dev/null`
Expected: all pass. Then `/opt/homebrew/bin/ruff check app` → `All checks passed!`.

- [ ] **Step 6: Update `CLAUDE.md`** — in the "Additional domains" table, in the Progress row, change the domain cell from `**Progress** (UX-D1, UX-D2)` to `**Progress** (UX-D1, UX-D2, UX-D3)` and append this text at the end of the Notes cell, directly before its final ` Independent of the pet. |`:

```markdown
 **Weekly quest** (D3): one personal goal per kid per Mon–Sun week — `on_time` / `extra_mile` / `perfect_days` / `go_getter`, picked by rotation and sized ~10 % above the kid's last 4 weeks (`quest_service.py`; copy only in `frontend/src/lib/quest.ts`). Only the week's row is stored (`weekly_quests`: type, target, bonus, paid/seen); progress is derived on read with the same strict rule as badges (pending review does not count). `GET /api/progress/quest` **writes**: it creates the week's quest and pays the bonus once (a `bonus` point transaction; guarded UPDATE on `rewarded_at`), also settling LAST week's quest. The bonus is `families.quest_bonus_points` (default 20; **0 switches quests off**), copied onto the row at creation. The done moment is a card state with confetti, never a modal.
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/progress.py backend/app/schemas/oversight.py backend/app/services/oversight_service.py backend/tests/test_quest_api.py CLAUDE.md
git commit -m "feat(ux-d3): weekly quest endpoints + quest fields on the parent hub"
```

---

### Task 5: Frontend view-model — `lib/quest.ts` + hub chip

**Files:**
- Create: `frontend/src/lib/quest.ts`
- Modify: `frontend/src/lib/parentHub.ts` (`kidRowView`)
- Test: `frontend/test/quest.test.ts`; modify `frontend/test/parent-hub.test.ts`

**Interfaces:**
- Consumes: the Task 4 JSON (`{ applies, gig_term, quest, celebrate }`), `KidSummary.quest_progress / quest_target / quest_done`, existing `gigTerm(term, lang)` from `frontend/src/lib/gigTerm.ts` (returns `{ one, many, One, Many }`), existing `progressLine(kid, lang)` from `frontend/src/lib/progress.ts`.
- Produces (`frontend/src/lib/quest.ts`): `type Lang = "es" | "en"`; `QUEST_META: Record<string, { emoji: string; title: (n, lang, gig) => string }>`; `interface QuestCardView { emoji; title; progressLabel; barPct; daysLeftLabel; bonusLabel; done }`; `interface QuestCelebrateView { id; emoji; heading; bonusLabel }`; `interface QuestView { card: QuestCardView | null; celebrate: QuestCelebrateView | null }`; `questView(resp: any, lang: Lang, starMode?: boolean): QuestView | null`; `interface QuestDomUpdate { showDone; emoji; title; progressLabel; barWidthPct; daysLeftLabel; bonusLabel; doneHeading; doneBonusLabel }`; `questDomUpdate(view: QuestView, lang: Lang): QuestDomUpdate`; `questChip(kid: any): string | null`.
- Produces (`parentHub.ts`): `kidRowView(...).progressLine` now ends with ` · 🏁 3/5` (or ` · 🏁 ✓`) when the kid has a quest.

- [ ] **Step 1: Install dependencies** (once per worktree), from `frontend/`:

Run: `timeout 600 npm ci </dev/null 2>&1 | tail -2`
Expected: `added … packages` with no error.

- [ ] **Step 2: Write the failing tests** — `frontend/test/quest.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { QUEST_META, questChip, questDomUpdate, questView } from "../src/lib/quest";

const quest = (over: Record<string, unknown> = {}) => ({
    id: "q1", quest: "on_time", target: 5, progress: 3, bonus_points: 20,
    week_start: "2026-09-28", days_left: 4, completed: false, ...over,
});
const resp = (over: Record<string, unknown> = {}) => ({
    applies: true, gig_term: "gig", quest: quest(), celebrate: null, ...over,
});

describe("quest copy", () => {
    it("has the four spec quests", () => {
        expect(Object.keys(QUEST_META)).toEqual(["on_time", "extra_mile", "perfect_days", "go_getter"]);
        expect(Object.values(QUEST_META).map((m) => m.emoji)).toEqual(["⏰", "🚀", "✨", "💼"]);
    });
});

describe("questView", () => {
    it("returns null without a usable response", () => {
        expect(questView(null, "es")).toBeNull();
        expect(questView(undefined, "es")).toBeNull();
        expect(questView({ applies: false }, "es")).toBeNull();
        expect(questView({ applies: true, quest: null, celebrate: null }, "es")).toBeNull();
    });

    it("builds the in-progress card", () => {
        expect(questView(resp(), "es")!.card).toEqual({
            emoji: "⏰", title: "Termina 5 tareas a tiempo", progressLabel: "3/5", barPct: 60,
            daysLeftLabel: "Quedan 4 días", bonusLabel: "+20 puntos", done: false,
        });
        expect(questView(resp(), "en")!.card).toMatchObject({
            title: "Finish 5 chores on time", daysLeftLabel: "4 days left", bonusLabel: "+20 points",
        });
        expect(questView(resp(), "es")!.celebrate).toBeNull();
    });

    it("uses singular forms at one", () => {
        const one = (key: string) => questView(resp({ quest: quest({ quest: key, target: 1, progress: 0 }) }), "es")!.card!.title;
        expect(one("on_time")).toBe("Termina 1 tarea a tiempo");
        expect(one("perfect_days")).toBe("Logra 1 día perfecto");
        expect(one("extra_mile")).toBe("Haz 1 tarea extra");
        expect(one("go_getter")).toBe("Logra 1 gig aprobada");
        const en = (key: string) => questView(resp({ quest: quest({ quest: key, target: 1, progress: 0 }) }), "en")!.card!.title;
        expect(en("on_time")).toBe("Finish 1 chore on time");
        expect(en("perfect_days")).toBe("Have 1 perfect day");
        expect(en("extra_mile")).toBe("Do 1 bonus task");
        expect(en("go_getter")).toBe("Get 1 gig approved");
    });

    it("uses plural forms and the family's word for a gig", () => {
        const t = (key: string, term = "gig", lang: "es" | "en" = "es") =>
            questView(resp({ gig_term: term, quest: quest({ quest: key, target: 2, progress: 0 }) }), lang)!.card!.title;
        expect(t("perfect_days")).toBe("Logra 2 días perfectos");
        expect(t("extra_mile")).toBe("Haz 2 tareas extra");
        expect(t("go_getter")).toBe("Logra 2 gigs aprobadas");
        expect(t("go_getter", "chamba")).toBe("Logra 2 chambas aprobadas");
        expect(t("go_getter", "gig", "en")).toBe("Get 2 gigs approved");
        expect(t("perfect_days", "gig", "en")).toBe("Have 2 perfect days");
        expect(t("extra_mile", "gig", "en")).toBe("Do 2 bonus tasks");
    });

    it("labels the last day and a one-point bonus", () => {
        const v = questView(resp({ quest: quest({ days_left: 1, bonus_points: 1 }) }), "es")!.card!;
        expect(v.daysLeftLabel).toBe("Último día");
        expect(v.bonusLabel).toBe("+1 punto");
        const en = questView(resp({ quest: quest({ days_left: 1, bonus_points: 1 }) }), "en")!.card!;
        expect(en.daysLeftLabel).toBe("Last day");
        expect(en.bonusLabel).toBe("+1 point");
    });

    it("shows stars instead of points for a star-mode kid", () => {
        expect(questView(resp(), "es", true)!.card!.bonusLabel).toBe("+20 ⭐");
    });

    it("never draws the bar past 100% and marks a paid quest done", () => {
        expect(questView(resp({ quest: quest({ progress: 9 }) }), "es")!.card!.barPct).toBe(100);
        const done = questView(resp({ quest: quest({ progress: 5, completed: true }) }), "es")!.card!;
        expect(done.done).toBe(true);
        expect(done.barPct).toBe(100);
    });

    it("drops a quest key it has no copy for", () => {
        expect(questView(resp({ quest: quest({ quest: "dragon" }) }), "es")).toBeNull();
        const v = questView(resp({
            quest: quest({ quest: "dragon" }),
            celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true },
        }), "es")!;
        expect(v.card).toBeNull();
        expect(v.celebrate).not.toBeNull();
    });

    it("builds the celebrate view, last week's or this week's", () => {
        const last = questView(resp({ celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true } }), "es")!;
        expect(last.celebrate).toEqual({
            id: "q0", emoji: "⏰", heading: "La misión de la semana pasada: ¡lograda!", bonusLabel: "+20 puntos",
        });
        const now = questView(resp({ celebrate: { id: "q1", quest: "on_time", target: 5, bonus_points: 20, last_week: false } }), "en")!;
        expect(now.celebrate).toMatchObject({ id: "q1", heading: "Quest done!", bonusLabel: "+20 points" });
        expect(questView(resp({ celebrate: { id: "q0", quest: "on_time", target: 3, bonus_points: 20, last_week: true } }), "en")!
            .celebrate!.heading).toBe("Last week's quest: done!");
    });

    it("still has a view when only last week's result is left to show", () => {
        const v = questView({ applies: true, gig_term: "gig", quest: null,
            celebrate: { id: "q0", quest: "extra_mile", target: 2, bonus_points: 20, last_week: true } }, "es")!;
        expect(v.card).toBeNull();
        expect(v.celebrate!.emoji).toBe("🚀");
    });
});

describe("questDomUpdate (what the card renders and what a live refresh writes)", () => {
    it("shows the progress block for a quest in progress", () => {
        expect(questDomUpdate(questView(resp(), "es")!, "es")).toEqual({
            showDone: false, emoji: "⏰", title: "Termina 5 tareas a tiempo", progressLabel: "3/5", barWidthPct: 60,
            daysLeftLabel: "Quedan 4 días", bonusLabel: "+20 puntos", doneHeading: "¡Misión lograda!", doneBonusLabel: "+20 puntos",
        });
    });
    it("shows the done block for a paid quest", () => {
        const u = questDomUpdate(questView(resp({ quest: quest({ progress: 5, completed: true }) }), "en")!, "en");
        expect(u.showDone).toBe(true);
        expect(u.doneHeading).toBe("Quest done!");
        expect(u.doneBonusLabel).toBe("+20 points");
    });
    it("shows last week's result first, over this week's quest in progress", () => {
        const u = questDomUpdate(questView(resp({
            celebrate: { id: "q0", quest: "extra_mile", target: 2, bonus_points: 30, last_week: true },
        }), "es")!, "es");
        expect(u.showDone).toBe(true);
        expect(u.doneHeading).toBe("La misión de la semana pasada: ¡lograda!");
        expect(u.doneBonusLabel).toBe("+30 puntos");
        expect(u.title).toBe("Termina 5 tareas a tiempo");       // this week's quest is ready underneath
    });
    it("copes with a celebrate-only view", () => {
        const u = questDomUpdate(questView({ applies: true, gig_term: "gig", quest: null,
            celebrate: { id: "q0", quest: "on_time", target: 2, bonus_points: 20, last_week: true } }, "en")!, "en");
        expect(u).toMatchObject({ showDone: true, title: "", progressLabel: "", barWidthPct: 0, doneHeading: "Last week's quest: done!" });
    });
});

describe("questChip (parent hub)", () => {
    it("shows progress, or a check when done", () => {
        expect(questChip({ quest_progress: 3, quest_target: 5, quest_done: false })).toBe("🏁 3/5");
        expect(questChip({ quest_progress: 5, quest_target: 5, quest_done: true })).toBe("🏁 ✓");
        expect(questChip({ quest_progress: 0, quest_target: 2, quest_done: false })).toBe("🏁 0/2");
    });
    it("is null when the kid has no quest", () => {
        expect(questChip({ quest_progress: null, quest_target: null, quest_done: false })).toBeNull();
        expect(questChip({})).toBeNull();
        expect(questChip(null)).toBeNull();
    });
});
```

In `frontend/test/parent-hub.test.ts`, inside the existing `describe("kidRowView progress line (UX-D1)", …)` block, add:

```ts
    it("adds the weekly quest chip to the row (UX-D3)", () => {
        const kid = { user_id: "k1", name: "Sofía", role: "child", streak_days: 5, rank: 4, badge_count: 3,
            quest_progress: 3, quest_target: 5, quest_done: false };
        expect(kidRowView(kid, null, new Date(), "es").progressLine).toBe("🔥 5 · Estrella · 🏅 3 · 🏁 3/5");
        expect(kidRowView({ ...kid, quest_done: true }, null, new Date(), "es").progressLine).toBe("🔥 5 · Estrella · 🏅 3 · 🏁 ✓");
    });
    it("shows the quest chip alone when there is no streak/rank data", () => {
        const v = kidRowView({ user_id: "k1", name: "Sofía", role: "child", quest_progress: 1, quest_target: 2, quest_done: false }, null, new Date(), "es");
        expect(v.progressLine).toBe("🏁 1/2");
    });
```

- [ ] **Step 3: Run — RED**

Run: `timeout 300 npx vitest run test/quest.test.ts test/parent-hub.test.ts </dev/null`
Expected: `quest.test.ts` fails to resolve `../src/lib/quest`; the two new `parent-hub` cases fail.

- [ ] **Step 4: Implement** — create `frontend/src/lib/quest.ts`:

```ts
/**
 * UX-D3 weekly quest view-model: the quest copy (the ONLY copy — goals and
 * progress come from the backend's quest_service.py) and the shapes the kid
 * home card and the parent hub render.
 */
import { gigTerm } from "./gigTerm";

export type Lang = "es" | "en";
type Gig = { one: string; many: string };

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

// Key order = the backend's rotation order. A key missing here is skipped.
export const QUEST_META: Record<string, { emoji: string; title: (n: number, lang: Lang, gig: Gig) => string }> = {
    on_time: {
        emoji: "⏰",
        title: (n, lang) => lang === "es"
            ? `Termina ${n} ${plural(n, "tarea", "tareas")} a tiempo`
            : `Finish ${n} ${plural(n, "chore", "chores")} on time`,
    },
    extra_mile: {
        emoji: "🚀",
        title: (n, lang) => lang === "es"
            ? `Haz ${n} ${plural(n, "tarea extra", "tareas extra")}`
            : `Do ${n} bonus ${plural(n, "task", "tasks")}`,
    },
    perfect_days: {
        emoji: "✨",
        title: (n, lang) => lang === "es"
            ? `Logra ${n} ${plural(n, "día perfecto", "días perfectos")}`
            : `Have ${n} perfect ${plural(n, "day", "days")}`,
    },
    go_getter: {
        emoji: "💼",
        title: (n, lang, gig) => lang === "es"
            ? `Logra ${n} ${plural(n, gig.one, gig.many)} ${plural(n, "aprobada", "aprobadas")}`
            : `Get ${n} ${plural(n, gig.one, gig.many)} approved`,
    },
};

export interface QuestCardView {
    emoji: string;
    title: string;
    progressLabel: string;
    barPct: number;
    daysLeftLabel: string;
    bonusLabel: string;
    /** The bonus was paid. */
    done: boolean;
}

export interface QuestCelebrateView {
    id: string;
    emoji: string;
    heading: string;
    bonusLabel: string;
}

export interface QuestView {
    /** This week's quest, or null when there is none (or its key is unknown). */
    card: QuestCardView | null;
    /** A paid quest the kid has not seen as done yet (last week's first). */
    celebrate: QuestCelebrateView | null;
}

const int = (v: unknown) => Math.max(0, Math.trunc(Number(v) || 0));

function bonusLabel(points: number, lang: Lang, starMode: boolean): string {
    if (starMode) return `+${points} ⭐`;
    return lang === "es" ? `+${points} ${plural(points, "punto", "puntos")}` : `+${points} ${plural(points, "point", "points")}`;
}

const doneHeading = (lang: Lang, lastWeek: boolean) =>
    lastWeek
        ? (lang === "es" ? "La misión de la semana pasada: ¡lograda!" : "Last week's quest: done!")
        : (lang === "es" ? "¡Misión lograda!" : "Quest done!");

export function questView(resp: any, lang: Lang, starMode = false): QuestView | null {
    if (!resp || resp.applies !== true) return null;
    const gig = gigTerm(String(resp.gig_term ?? "gig"), lang);

    let card: QuestCardView | null = null;
    const q = resp.quest;
    const meta = q ? QUEST_META[String(q.quest)] : undefined;
    if (q && meta) {
        const target = Math.max(1, int(q.target));
        const done = q.completed === true;
        const progress = done ? target : Math.min(int(q.progress), target);
        const days = Math.max(1, int(q.days_left));
        card = {
            emoji: meta.emoji,
            title: meta.title(target, lang, gig),
            progressLabel: `${progress}/${target}`,
            barPct: Math.round((progress / target) * 100),
            daysLeftLabel: days === 1
                ? (lang === "es" ? "Último día" : "Last day")
                : (lang === "es" ? `Quedan ${days} días` : `${days} days left`),
            bonusLabel: bonusLabel(int(q.bonus_points), lang, starMode),
            done,
        };
    }

    let celebrate: QuestCelebrateView | null = null;
    const c = resp.celebrate;
    const cMeta = c ? QUEST_META[String(c.quest)] : undefined;
    if (c && cMeta && c.id) {
        celebrate = {
            id: String(c.id),
            emoji: cMeta.emoji,
            heading: doneHeading(lang, c.last_week === true),
            bonusLabel: bonusLabel(int(c.bonus_points), lang, starMode),
        };
    }

    return card || celebrate ? { card, celebrate } : null;
}

/** Exactly what QuestCard.astro renders, and what its live refresh (on
 * `ftm:deck-empty`) writes back into the DOM. Pure so it is testable without one. */
export interface QuestDomUpdate {
    showDone: boolean;
    emoji: string;
    title: string;
    progressLabel: string;
    barWidthPct: number;
    daysLeftLabel: string;
    bonusLabel: string;
    doneHeading: string;
    doneBonusLabel: string;
}

export function questDomUpdate(view: QuestView, lang: Lang): QuestDomUpdate {
    const { card, celebrate } = view;
    return {
        // A result waiting to be seen wins over this week's progress.
        showDone: celebrate != null || card?.done === true,
        emoji: card?.emoji ?? celebrate?.emoji ?? "",
        title: card?.title ?? "",
        progressLabel: card?.progressLabel ?? "",
        barWidthPct: card?.barPct ?? 0,
        daysLeftLabel: card?.daysLeftLabel ?? "",
        bonusLabel: card?.bonusLabel ?? "",
        doneHeading: celebrate?.heading ?? doneHeading(lang, false),
        doneBonusLabel: celebrate?.bonusLabel ?? card?.bonusLabel ?? "",
    };
}

/** Parent hub chip for a kid's weekly quest: "🏁 3/5", "🏁 ✓", or null. */
export function questChip(kid: any): string | null {
    if (kid?.quest_target == null) return null;
    if (kid.quest_done === true) return "🏁 ✓";
    return `🏁 ${int(kid.quest_progress)}/${int(kid.quest_target)}`;
}
```

In `frontend/src/lib/parentHub.ts`: add `import { questChip } from "./quest";` next to the `progressLine` import, and in `kidRowView` replace the line `progressLine: progressLine(kid, lang),` with:

```ts
        // Streak · rank · badges (UX-D1/D2), then the weekly quest (UX-D3).
        progressLine: [progressLine(kid, lang), questChip(kid)].filter(Boolean).join(" · ") || null,
```

- [ ] **Step 5: Run — GREEN**

Run: `timeout 300 npx vitest run test/quest.test.ts test/parent-hub.test.ts test/progress.test.ts test/badges.test.ts </dev/null`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/quest.ts frontend/src/lib/parentHub.ts frontend/test/quest.test.ts frontend/test/parent-hub.test.ts
git commit -m "feat(ux-d3): weekly quest view-model + quest chip on the hub row"
```

---

### Task 6: Quest card on the kid home

**Files:**
- Create: `frontend/src/components/home/QuestCard.astro`
- Modify: `frontend/src/components/home/KidHome.astro`, `frontend/src/pages/dashboard.astro`
- Test: `frontend/test/quest-card.test.ts` (create)

**Interfaces:**
- Consumes: Task 5 `questView(resp, lang, starMode)`, `questDomUpdate(view, lang)`, `QuestView`; Task 4 `GET /api/progress/quest`, `POST /api/progress/quest/ack` body `{ id }`; existing `fireConfetti(host?: HTMLElement)` from `lib/celebrate.ts`; the existing `ftm:deck-empty` window event dispatched by `TaskDeck.astro`.
- Produces: `<QuestCard quest={QuestView} lang={lang} starMode={boolean} />`; `KidHome` accepts a new prop `quest: QuestView | null` and renders the card directly under the task deck.

- [ ] **Step 1: Write the failing tests** — create `frontend/test/quest-card.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(`../src/${p}`, import.meta.url)), "utf8");

describe("QuestCard (UX-D3)", () => {
    const src = read("components/home/QuestCard.astro");
    it("renders from questDomUpdate, the same mapping the live refresh uses", () => {
        expect(src).toMatch(/questDomUpdate\(\s*quest\s*,\s*lang\s*\)/);
        for (const slot of ["data-quest-title", "data-quest-progress", "data-quest-bar", "data-quest-days", "data-quest-bonus", "data-quest-done-heading", "data-quest-done-bonus"]) {
            expect(src).toContain(slot);
        }
    });
    it("switches blocks with the hidden ATTRIBUTE, never the hidden class", () => {
        expect(src).toMatch(/data-quest-progress-block\s+hidden=\{u\.showDone\}/);
        expect(src).toMatch(/data-quest-done-block\s+hidden=\{!u\.showDone\}/);
        expect(src).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("is not a modal", () => {
        expect(src).not.toMatch(/<dialog\b/);
        expect(src).not.toMatch(/showModal/);
    });
    it("celebrates once per quest id: confetti + one keepalive ack", () => {
        expect(src).toMatch(/const acked = new Set<string>\(\)/);
        expect(src.match(/\/api\/progress\/quest\/ack/g) ?? []).toHaveLength(1);
        expect(src).toMatch(/keepalive:\s*true/);
        expect(src).toMatch(/JSON\.stringify\(\{\s*id\s*\}\)/);
        expect(src).toMatch(/fireConfetti\(/);
    });
    it("keeps its confetti out of the way of a celebration modal on the same load", () => {
        expect(src).toMatch(/dialog\[open\]/);
    });
    it("refreshes when the deck is emptied", () => {
        expect(src).toMatch(/addEventListener\(\s*["']ftm:deck-empty["']/);
        expect(src).toMatch(/fetch\(\s*["']\/api\/progress\/quest["']/);
    });
    it("puts no emoji in a heading and uses no h1", () => {
        expect(src).not.toMatch(/<h1\b/);
    });
});

describe("kid home wiring (UX-D3)", () => {
    const home = read("components/home/KidHome.astro");
    const dash = read("pages/dashboard.astro");
    it("KidHome takes the quest view and renders the card only when there is one", () => {
        expect(home).toMatch(/quest:\s*QuestView\s*\|\s*null/);
        expect(home).toMatch(/\{\s*quest\s*&&\s*<QuestCard\b/);
    });
    it("the card sits directly under the task deck", () => {
        const deckIdx = home.indexOf("<TaskDeck");
        const cardIdx = home.indexOf("<QuestCard");
        const reviewIdx = home.indexOf("inReview > 0");
        expect(deckIdx).toBeGreaterThan(-1);
        expect(cardIdx).toBeGreaterThan(deckIdx);
        expect(reviewIdx).toBeGreaterThan(cardIdx);
    });
    it("the dashboard fetches the quest with its other calls and passes the view down", () => {
        expect(dash).toMatch(/apiFetch<any>\("\/api\/progress\/quest",\s*\{\s*token\s*\}\)/);
        expect(dash).toMatch(/const quest = questView\(questResp,\s*lang,\s*starMode\)/);
        expect(dash).toMatch(/<KidHome[\s\S]*?quest=\{quest\}/);
    });
});
```

- [ ] **Step 2: Run — RED**

Run: `timeout 300 npx vitest run test/quest-card.test.ts </dev/null`
Expected: FAIL — `ENOENT … QuestCard.astro`; the wiring block fails on the missing prop and fetch.

- [ ] **Step 3: Implement the card** — create `frontend/src/components/home/QuestCard.astro`:

```astro
---
/**
 * UX-D3 weekly quest card on the kid home. One card, two states: in progress
 * (goal, bar, days left, prize) and done. The done moment is celebrated HERE
 * — confetti once + an ack — never in a modal, so it cannot clash with the
 * welcome tour or the rank-up / badge celebrations. Rendered from
 * questDomUpdate(), the same mapping the live refresh writes back.
 */
import { questDomUpdate, type QuestView } from "../../lib/quest";

interface Props {
    quest: QuestView;
    lang: "es" | "en";
    starMode: boolean;
}
const { quest, lang, starMode } = Astro.props;
const es = lang === "es";
const u = questDomUpdate(quest, lang);
---

<section data-quest-card data-lang={lang} data-star={starMode ? "1" : "0"} data-celebrate-id={quest.celebrate?.id ?? ""}
         class="rounded-2xl border border-brand-ink/10 bg-white p-4 shadow-[var(--shadow-card)]">
    <h2 class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">{es ? "Misión de la semana" : "Quest of the week"}</h2>

    <div data-quest-progress-block hidden={u.showDone} class="mt-2">
        <div class="flex items-center gap-3">
            <span class="text-2xl leading-none" aria-hidden="true" data-quest-emoji>{u.emoji}</span>
            <p class="min-w-0 flex-1 font-bold text-brand-ink" data-quest-title>{u.title}</p>
            <span class="text-sm font-extrabold tabular-nums text-brand-ink" data-quest-progress>{u.progressLabel}</span>
        </div>
        <div class="mt-2 h-2 overflow-hidden rounded-full bg-brand-ink/10">
            <div class="h-full bg-brand-mint" data-quest-bar style={`width:${u.barWidthPct}%`}></div>
        </div>
        <p class="mt-2 flex items-center justify-between gap-2 text-xs font-bold text-brand-ink-soft">
            <span data-quest-days>{u.daysLeftLabel}</span>
            <span class="text-brand-mint-text" data-quest-bonus>{u.bonusLabel}</span>
        </p>
    </div>

    <div data-quest-done-block hidden={!u.showDone} class="mt-2 rounded-xl bg-brand-mint px-3 py-3 text-brand-ink">
        <p class="font-display text-lg font-extrabold">
            <span aria-hidden="true">🏁 </span><span data-quest-done-heading>{u.doneHeading}</span>
        </p>
        <p class="text-sm font-bold" data-quest-done-bonus>{u.doneBonusLabel}</p>
    </div>
</section>

<script>
    import { fireConfetti } from "../../lib/celebrate";
    import { questDomUpdate, questView } from "../../lib/quest";

    const card = document.querySelector<HTMLElement>("[data-quest-card]");
    if (card) {
        const lang = card.dataset.lang === "en" ? "en" : "es";
        const star = card.dataset.star === "1";

        // One celebration per quest id, however many times it is reported.
        const acked = new Set<string>();
        const celebrate = (id: string) => {
            if (!id || acked.has(id)) return;
            acked.add(id);
            fetch("/api/progress/quest/ack", {
                method: "POST",
                credentials: "same-origin",
                keepalive: true,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id }),
            }).catch(() => {});
            // Let a rank-up / badge modal on this load open first: confetti on
            // the page would paint under its backdrop and block the modal's own.
            window.setTimeout(() => {
                if (!document.querySelector("dialog[open]")) fireConfetti();
            }, 600);
        };
        celebrate(card.dataset.celebrateId ?? "");

        const text = (sel: string, value: string) => {
            const el = card.querySelector(sel);
            if (el) el.textContent = value;
        };
        const refresh = async () => {
            try {
                const res = await fetch("/api/progress/quest", { credentials: "same-origin" });
                if (!res.ok) return;
                const view = questView(await res.json(), lang, star);
                if (!view) return;
                const u = questDomUpdate(view, lang);
                text("[data-quest-emoji]", u.emoji);
                text("[data-quest-title]", u.title);
                text("[data-quest-progress]", u.progressLabel);
                text("[data-quest-days]", u.daysLeftLabel);
                text("[data-quest-bonus]", u.bonusLabel);
                text("[data-quest-done-heading]", u.doneHeading);
                text("[data-quest-done-bonus]", u.doneBonusLabel);
                const bar = card.querySelector<HTMLElement>("[data-quest-bar]");
                if (bar) bar.style.width = `${u.barWidthPct}%`;
                card.querySelector<HTMLElement>("[data-quest-progress-block]")?.toggleAttribute("hidden", u.showDone);
                card.querySelector<HTMLElement>("[data-quest-done-block]")?.toggleAttribute("hidden", !u.showDone);
                celebrate(view.celebrate?.id ?? "");
            } catch {
                // Best-effort refresh; the server-rendered card stays as it was.
            }
        };
        // TaskDeck dispatches this when the day's deck is emptied — the same
        // moment the streak pill refreshes.
        window.addEventListener("ftm:deck-empty", refresh);
    }
</script>
```

- [ ] **Step 4: Wire it in**

`frontend/src/components/home/KidHome.astro`:
- add imports next to the existing ones:

```astro
import QuestCard from "./QuestCard.astro";
import type { QuestView } from "../../lib/quest";
```

- add to `Props` (after the `pet:` line):

```astro
    /** UX-D3 weekly quest; null = no quest this week (or the call failed). */
    quest: QuestView | null;
```

- add `quest` to the destructuring of `Astro.props`;
- extend the header comment's first sentence to mention the quest card ("…task deck, weekly quest card, in-review chip…");
- render the card directly after the closing `/>` of `<TaskDeck … />` and before the `{inReview > 0 && (` block:

```astro
    {quest && <QuestCard quest={quest} lang={lang} starMode={starMode} />}
```

`frontend/src/pages/dashboard.astro`:
- import: `import { questView } from "../lib/quest";` next to the other `../lib` imports;
- in the second `Promise.all` (the one that already fetches `/api/progress/me` and `/api/progress/badges`), add `{ data: questResp }` as the LAST entry of the destructuring and this as the LAST call:

```astro
        // UX-D3. apiFetch never throws; null → no quest card.
        apiFetch<any>("/api/progress/quest", { token }),
```

- directly after the existing `const badges = badgesView(badgesResp, lang);` line add:

```astro
const quest = questView(questResp, lang, starMode);
```

- pass it to `<KidHome … />` by adding the attribute `quest={quest}` after `pet={…}`.

- [ ] **Step 5: Run — GREEN**

Run: `timeout 300 npx vitest run test/quest-card.test.ts test/kid-home.test.ts test/badge-celebration.test.ts test/progress.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts </dev/null`
Expected: all pass. If the visual guard flags a class from this task, fix the class to satisfy the rule it names — do not weaken the guard. Then `timeout 600 npm run check </dev/null 2>&1 | tail -4` → `0 errors`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/home/QuestCard.astro frontend/src/components/home/KidHome.astro frontend/src/pages/dashboard.astro frontend/test/quest-card.test.ts
git commit -m "feat(ux-d3): weekly quest card on the kid home, celebrated in place"
```

---

### Task 7: Parent setting, user guides, full verification

**Files:**
- Modify: `frontend/src/pages/parent/settings/family.astro`
- Modify: `docs/USER_GUIDE_EN.md`, `docs/USER_GUIDE_ES.md`
- Test: `frontend/test/quest-settings.test.ts` (create)

**Interfaces:**
- Consumes: Task 2 `quest_bonus_points` on `GET /api/families/me` (already fetched by this page as `family`) and on `PATCH /api/families/me` (parent only; `0–500`).
- Produces: a "Weekly quest" section on parent settings → Family with a number field `#quest-bonus` and a save button `#quest-save`.

- [ ] **Step 1: Write the failing tests** — create `frontend/test/quest-settings.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = readFileSync(fileURLToPath(new URL("../src/pages/parent/settings/family.astro", import.meta.url)), "utf8");

describe("family settings — weekly quest bonus (UX-D3)", () => {
    it("has a bounded number field pre-filled from the family", () => {
        const input = src.match(/<input[^>]*id="quest-bonus"[^>]*>/s)?.[0] ?? "";
        expect(input).not.toBe("");
        expect(input).toMatch(/type="number"/);
        expect(input).toMatch(/min="0"/);
        expect(input).toMatch(/max="500"/);
        expect(input).toMatch(/value=\{family\?\.quest_bonus_points \?\? 20\}/);
    });
    it("explains that zero switches quests off, in both languages", () => {
        expect(src).toContain("0 desactiva las misiones semanales");
        expect(src).toContain("0 turns weekly quests off");
    });
    it("saves through the existing family update with the right field", () => {
        expect(src).toMatch(/quest_bonus_points:\s*value/);
        expect(src).toMatch(/id="quest-save"/);
    });
    it("rejects values outside 0–500 before calling the API", () => {
        expect(src).toMatch(/value < 0 \|\| value > 500/);
        expect(src).toMatch(/Number\.isInteger\(value\)/);
    });
});
```

- [ ] **Step 2: Run — RED**

Run: `timeout 300 npx vitest run test/quest-settings.test.ts </dev/null`
Expected: all 4 FAIL (no `#quest-bonus` field).

- [ ] **Step 3: Implement the setting** — in `frontend/src/pages/parent/settings/family.astro`:

Insert this section directly after the closing `</form>` of `<form id="family-form" …>` and before the modules section (`<section … id="modules-section">`):

```astro
    <section class="mt-4 bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10 space-y-3" id="quest-section"
             data-saved={lang === "es" ? "Guardado." : "Saved."}
             data-error={lang === "es" ? "No se pudo guardar. Intenta de nuevo." : "Could not save. Try again."}
             data-range={lang === "es" ? "Usa un número entero de 0 a 500." : "Use a whole number from 0 to 500."}>
        <h2 class="text-sm font-bold text-brand-ink">🏁 {lang === "es" ? "Misión semanal" : "Weekly quest"}</h2>
        <div>
            <label for="quest-bonus" class="block text-sm font-semibold text-brand-ink mb-1">
                {lang === "es" ? "Bono de la misión semanal (puntos)" : "Weekly quest bonus (points)"}
            </label>
            <input type="number" id="quest-bonus" name="quest_bonus_points" inputmode="numeric" min="0" max="500" step="1"
                   value={family?.quest_bonus_points ?? 20}
                   class="w-32 rounded-lg border border-brand-ink/20 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-sky" />
            <p class="text-xs text-brand-ink-soft mt-1">
                {lang === "es"
                    ? "Cada niño recibe una misión personal por semana y gana este bono al lograrla. 0 desactiva las misiones semanales."
                    : "Each kid gets one personal quest per week and earns this bonus for reaching it. 0 turns weekly quests off."}
            </p>
        </div>
        <div class="flex items-center gap-3">
            <button type="button" id="quest-save" class={`disabled:opacity-60 ${buttonClass("secondary", "sm")}`}>
                {lang === "es" ? "Guardar" : "Save"}
            </button>
            <span id="quest-status" class="text-sm" aria-live="polite"></span>
        </div>
    </section>
```

Add this script at the very end of the file (after the existing `</script>`); it is a plain hoisted script with no imports, separate from the page's `define:vars` script:

```astro
<script>
    const section = document.getElementById("quest-section");
    const input = document.getElementById("quest-bonus") as HTMLInputElement | null;
    const save = document.getElementById("quest-save") as HTMLButtonElement | null;
    const status = document.getElementById("quest-status");
    save?.addEventListener("click", async () => {
        if (!section || !input || !status) return;
        const value = Number(input.value);
        status.className = "text-sm";
        if (!Number.isInteger(value) || value < 0 || value > 500) {
            status.textContent = section.dataset.range ?? "";
            status.className = "text-sm text-red-700";
            return;
        }
        save.setAttribute("disabled", "true");
        status.textContent = "";
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ quest_bonus_points: value }),
            });
            status.textContent = r.ok ? (section.dataset.saved ?? "") : (section.dataset.error ?? "");
            status.className = r.ok ? "text-sm text-green-700" : "text-sm text-red-700";
        } catch {
            status.textContent = section.dataset.error ?? "";
            status.className = "text-sm text-red-700";
        } finally {
            save.removeAttribute("disabled");
        }
    });
</script>
```

- [ ] **Step 4: Run — GREEN**

Run: `timeout 300 npx vitest run test/quest-settings.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts </dev/null`
Expected: all pass.

- [ ] **Step 5: User guides** — add a section at the end of Chapter 17.5 (directly before `# Chapter 18: Virtual Pet` / `# Capitulo 18: Mascota Virtual`). The chapter's table-of-contents entry is a nested bullet under Chapter 17; add nothing to the table of contents.

`docs/USER_GUIDE_EN.md`:

```markdown
## 17.5.4 Weekly Quest

Every week (Monday to Sunday) each kid and teen gets one personal quest. It appears as a card on their home screen, under their tasks.

| Quest | Goal |
|---|---|
| On time | Finish a number of chores on the day they are due |
| Perfect days | Have a number of days where every chore was done on time |
| Extra mile | Do a number of bonus tasks |
| Go-getter | Get a number of gigs approved |

The quest changes from week to week, and the goal is sized to each kid: a little above what they did in recent weeks, and never more than they can still reach. Once the week's quest is set, its goal does not change.

Reaching the goal pays a points bonus once. Chores and bonus tasks that need a parent's review count once they are approved, so the bonus can arrive after the parent approves — even early the following week.

> **For parents:** each kid's row on your home screen shows their quest (🏁 3/5, or 🏁 ✓ when done). You set the bonus in **Settings → Family → Weekly quest** (20 points by default). Setting it to 0 turns weekly quests off.
```

`docs/USER_GUIDE_ES.md` (no accents, like the rest of that guide):

```markdown
## 17.5.4 Mision Semanal

Cada semana (lunes a domingo) cada nino y adolescente recibe una mision personal. Aparece como una tarjeta en su pantalla de inicio, debajo de sus tareas.

| Mision | Meta |
|---|---|
| A tiempo | Terminar cierto numero de tareas el dia que tocan |
| Dias perfectos | Lograr cierto numero de dias con todas las tareas hechas a tiempo |
| Milla extra | Hacer cierto numero de tareas extra |
| Emprendedor | Lograr cierto numero de gigs aprobadas |

La mision cambia de una semana a otra, y la meta se ajusta a cada nino: un poco arriba de lo que hizo en las semanas recientes, y nunca mas de lo que todavia puede alcanzar. Una vez fijada la mision de la semana, su meta no cambia.

Lograr la meta paga un bono de puntos una sola vez. Las tareas y tareas extra que requieren revision de un papa cuentan cuando se aprueban, asi que el bono puede llegar despues de que el papa apruebe — incluso al inicio de la semana siguiente.

> **Para papas:** la fila de cada hijo en su pantalla de inicio muestra su mision (🏁 3/5, o 🏁 ✓ cuando esta lograda). El bono se configura en **Ajustes → Familia → Mision semanal** (20 puntos por defecto). Ponerlo en 0 desactiva las misiones semanales.
```

- [ ] **Step 6: Full frontend verification** (from `frontend/`):

- `timeout 600 npx vitest run </dev/null 2>&1 | grep -E 'Test Files|Tests '` → all pass (incl. the strict visual guard and the no-native-dialogs guard).
- `timeout 600 npm run check </dev/null 2>&1 | tail -4` → `0 errors`.
- `timeout 900 npm run build </dev/null > /private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/d3-build.log 2>&1; echo exit=$?; tail -1 /private/tmp/claude-501/-Users-jc-dev-2026-AgentIA-family-task-manager/374ee353-f0f7-4619-bd3b-07b8ea8da0a8/scratchpad/d3-build.log` → `exit=0`, last line `Complete!`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/parent/settings/family.astro frontend/test/quest-settings.test.ts docs/USER_GUIDE_EN.md docs/USER_GUIDE_ES.md
git commit -m "feat(ux-d3): weekly quest bonus setting for parents + guides"
```

---

## After the last task (controller, not an implementer)

1. Backend, one run, nothing else using the test DB: `tests/test_quest_rules.py tests/test_quest_model.py tests/test_quest_service.py tests/test_quest_api.py tests/test_badge_rules.py tests/test_badge_model.py tests/test_badge_service.py tests/test_badge_api.py tests/test_progress_rules.py tests/test_progress_service.py tests/test_progress_api.py tests/test_family_delete_export.py tests/test_oversight.py tests/test_oversight_today_fields.py tests/test_parent_nudge.py` plus any test file that exercises family settings or points (`grep -rl "families/me\|PointsService" tests/*.py`) → all pass; `/opt/homebrew/bin/ruff check app` clean.
2. Whole-branch review (most capable model), one fix wave, scoped re-review.
3. Push → PR → watch CI (full backend suite + migration round-trip + frontend) → merge explicitly once green → sync main → `./scripts/deploy-onprem.sh -y` → verify running images.
4. Prod check, demo family `b8312b5a-c9c0-469f-992f-8dbd412db4a7` only, at 390 px: `sofia.demo` and `diego.demo` — the quest card shows under the deck with a sensible goal; `mariana.demo` hub rows show the 🏁 chip; Settings → Family shows the field at 20, saving 0 hides the card, then restore 20. Never touch the real family `1998e48d-2ef0-48b6-a437-cbb730ae935c`.
