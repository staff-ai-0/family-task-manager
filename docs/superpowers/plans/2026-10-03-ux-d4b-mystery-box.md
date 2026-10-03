# UX-D4b Mystery Box Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A kid who finishes every chore of the day gets a closed box on their home that opens to a surprise from the parents' jar, or a points bonus when the jar is empty; parents fill the jar and mark surprises delivered.

**Architecture:** Two family-scoped tables (`mystery_surprises` = the jar, `mystery_boxes` = one row per kid per perfect day) and a three-state family setting. Like badges and quests, the box is created on read (`GET /api/progress/mystery`) and its content is decided and paid once at opening (guarded UPDATE). No job, no notification, no LLM.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest · Astro 5 + vitest (node; source-structure tests for `.astro`).

**Spec:** `docs/superpowers/specs/2026-10-03-ux-d4b-mystery-box-design.md`

## Global Constraints

- Family isolation: every query filters by `family_id`; a kid reads/opens only their own boxes.
- Kids and teens only (`KID_ROLES`); parents get `applies: false`.
- Perfect day = `ProgressService.day_states(...)[today] == DayState.done` (the streak's rule, counted at submit).
- One box per kid per day: `UNIQUE(family_id, user_id, day)` (`uq_mystery_boxes_family_user_day`). Content decided at opening; pay-once by guarded `UPDATE … WHERE opened_at IS NULL RETURNING`.
- Points fallback: `random.randint(max(1, M // 4), M)` with `M = families.mystery_box_points`. Jar pick: random active surprise, excluding the kid's most recent one when the jar has ≥ 2.
- `families.mystery_box_points`: NULL undecided (off + hub card), 0 off, > 0 on. Migration `mystery_box` (down-revision `teen_checkins`): `ADD COLUMN … DEFAULT 20` then `UPDATE families SET mystery_box_points = NULL`.
- Jar: ≤ 20 surprises per family; title 1–60 chars trimmed; emoji ≤ 4 chars optional.
- Copy only in `frontend/src/lib/mystery.ts`. Browser paths need Astro route files (`/api/progress/[...path].ts` exists; `/api/families/surprises/[...path].ts` is new) — keep the guard test.
- No native `alert`/`confirm`/`prompt`; kit classes; `hidden` attribute (not class); emoji never in an `<h1>`.
- Tests never hard-code a calendar date; dates derive from the family's today.
- Local backend tests: `$SP/jpt.sh`-style env (`TZ=UTC`, test DB on 5435, `--no-cov`), named files only; lint `/opt/homebrew/bin/ruff check app`. Frontend: `npm ci` once, `npx vitest run <files>`, `npm run check`, `npm run build`.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **Pay once** — two opens of the same box (double tap, two devices) credit the points once and both callers see the same content (Task 2).
2. **A perfect day that is later un-perfected** (a chore rejected after the box opened) must not take the box back, and a day with only bonus tasks or no chores must create none (Task 2).
3. **Cross-kid / cross-family** — opening a sibling's box or another family's box is a 404 and stores nothing; a parent cannot mark another family's delivery (Tasks 2, 3).
4. **Family switched off after a box appeared** — opening is refused (409) and the box stays; it opens once the family is on again (Task 2).
5. **The card must appear without a reload** when the last chore is done (`ftm:deck-empty` → refetch), and the opening animation must never block a second box (Task 5).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/mystery.py` (new) | `MysterySurprise`, `MysteryBox` |
| `backend/migrations/versions/2026_10_03_mystery_box.py` (new) | tables + `families.mystery_box_points` |
| `backend/app/models/{__init__,family}.py`, `backend/app/schemas/family.py`, `backend/app/services/family_export_service.py` | registration, column, schema, export |
| `backend/app/services/mystery_service.py` (new) | rules, `sync`, `open`, deliveries, jar |
| `backend/app/schemas/progress.py`, `backend/app/api/routes/progress.py`, `backend/app/api/routes/families.py` | schemas + routes |
| `frontend/src/lib/mystery.ts` (new), `frontend/src/components/home/MysteryBoxCard.astro` (new), `KidHome.astro`, `pages/dashboard.astro` | kid card |
| `frontend/src/components/home/DeliverStrip.astro` (new), `pages/parent/index.astro`, `pages/parent/settings/family.astro`, `pages/api/families/surprises/[...path].ts` (new) | parent side |
| `docs/USER_GUIDE_{EN,ES}.md`, `CLAUDE.md` | docs |

---

### Task 1: Tables, family setting, export

**Files:**
- Create: `backend/app/models/mystery.py`, `backend/migrations/versions/2026_10_03_mystery_box.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/family.py`, `backend/app/schemas/family.py`, `backend/app/services/family_export_service.py`
- Test: `backend/tests/test_mystery_model.py`

**Interfaces:**
- Produces: `MysterySurprise(id, family_id, title, emoji, created_by, created_at)`; `MysteryBox(id, family_id, user_id, day, kind, surprise_id, surprise_title, surprise_emoji, points, opened_at, delivered_at, delivered_by, created_at)`; constraint names `uq_mystery_boxes_family_user_day`, `ck_mystery_boxes_kind`, `ck_mystery_boxes_opened_iff_kind`, `ck_mystery_boxes_points`; `Family.mystery_box_points: Optional[int]`; `FamilyUpdate.mystery_box_points` (`ge=0, le=500`); `FamilyResponse.mystery_box_points: Optional[int]`; export files `progress/mystery_surprises.json`, `progress/mystery_boxes.json`.

- [ ] **Step 1: Write the failing tests**

```python
"""UX-D4b mystery box: the two tables, their guards, the family setting, the export."""
import importlib.util
import pathlib
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.mystery import MysteryBox, MysterySurprise
from app.services.family_export_service import EXPORTED_FAMILY_TABLES
from app.services.progress_service import ProgressService

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "2026_10_03_mystery_box.py"
RESET_TO_NULL = re.compile(r"^\s*UPDATE\s+families\s+SET\s+mystery_box_points\s*=\s*NULL\s*;?\s*$", re.IGNORECASE)


class _RecordingOp:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("mystery_box", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(direction):
    mod = _load()
    op = _RecordingOp()
    mod.op = op
    getattr(mod, direction)()
    return op.calls


def test_revision_chain():
    mod = _load()
    assert mod.revision == "mystery_box" and mod.down_revision == "teen_checkins"


def test_existing_families_start_undecided_and_new_ones_at_twenty():
    calls = _run("upgrade")
    adds = [(i, a) for i, (n, a, _k) in enumerate(calls) if n == "add_column" and a[0] == "families"]
    assert len(adds) == 1
    at, (_table, column) = adds[0]
    assert column.name == "mystery_box_points" and column.nullable is True
    assert str(column.server_default.arg) == "20"
    resets = [i for i, (n, a, _k) in enumerate(calls) if n == "execute" and RESET_TO_NULL.match(str(a[0]))]
    assert len(resets) == 1 and resets[0] > at                  # the reset runs AFTER the column exists
    tables = [a[0] for n, a, _k in calls if n == "create_table"]
    assert tables == ["mystery_surprises", "mystery_boxes"]


def test_reverse_migration_removes_everything():
    calls = _run("downgrade")
    assert ("drop_table", ("mystery_boxes",), {}) in calls
    assert ("drop_table", ("mystery_surprises",), {}) in calls
    assert ("drop_column", ("families", "mystery_box_points"), {}) in calls


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


def _box(kid, day, **kw):
    base = dict(family_id=kid.family_id, user_id=kid.id, day=day, kind=None, surprise_id=None, surprise_title=None,
                surprise_emoji=None, points=0, opened_at=None, created_at=datetime.now(timezone.utc))
    base.update(kw)
    return MysteryBox(**base)


class TestTables:
    async def test_a_closed_box_and_a_surprise_are_stored(self, db_session, test_family, test_parent_user, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add_all([
            _box(test_child_user, today),
            MysterySurprise(family_id=test_family.id, title="Pick dessert tonight", emoji="🍨", created_by=test_parent_user.id),
        ])
        await db_session.commit()
        box = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert box.opened_at is None and box.kind is None and box.points == 0
        jar = (await db_session.execute(select(MysterySurprise))).scalar_one()
        assert (jar.title, jar.emoji) == ("Pick dessert tonight", "🍨")

    async def test_one_box_per_kid_per_day(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add(_box(test_child_user, today))
        await db_session.commit()
        db_session.add(_box(test_child_user, today))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    @pytest.mark.parametrize("bad", [
        dict(kind="coins"),                                              # unknown kind
        dict(kind="points", points=12),                                  # a kind without opened_at
        dict(opened_at=datetime.now(timezone.utc)),                      # opened without a kind
        dict(kind="points", points=-1, opened_at=datetime.now(timezone.utc)),
    ])
    async def test_the_database_refuses_inconsistent_boxes(self, db_session, test_family, test_child_user, bad):
        today = await _today(db_session, test_family.id)
        db_session.add(_box(test_child_user, today, **bad))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()


class TestFamilySetting:
    async def test_a_test_family_reads_twenty_by_default(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["mystery_box_points"] == 20

    async def test_parent_sets_it_within_bounds(self, client, auth_headers, db_session, test_family):
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 35}, headers=auth_headers)).json()["mystery_box_points"] == 35
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 0}, headers=auth_headers)).status_code == 200
        assert (await client.patch("/api/families/me", json={"mystery_box_points": -1}, headers=auth_headers)).status_code == 422
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 501}, headers=auth_headers)).status_code == 422
        await db_session.refresh(test_family)
        assert test_family.mystery_box_points == 0

    async def test_an_undecided_family_reads_null(self, client, auth_headers, db_session, test_family):
        test_family.mystery_box_points = None
        await db_session.commit()
        assert (await client.get("/api/families/me", headers=auth_headers)).json()["mystery_box_points"] is None


def test_both_tables_are_part_of_the_family_export():
    assert {"mystery_surprises", "mystery_boxes"} <= EXPORTED_FAMILY_TABLES
```

- [ ] **Step 2: Run** `pytest tests/test_mystery_model.py` — Expected: FAIL at import.

- [ ] **Step 3: Implement**

`backend/app/models/mystery.py`:

```python
"""UX-D4b mystery box.

mystery_surprises — the family's jar: short real-life surprises parents write
once ("pick dessert tonight"); reusable, picked at random.
mystery_boxes — one row per kid per PERFECT day (every non-bonus chore done).
Created closed when the kid's home reads progress; the content (a jar
surprise, or a points bonus when the jar is empty) is decided and paid once
at opening. The surprise's title is copied onto the box so a deleted jar item
still reads right.
"""
import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class MysterySurprise(Base):
    __tablename__ = "mystery_surprises"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(60), nullable=False)
    emoji = Column(String(4), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MysteryBox(Base):
    __tablename__ = "mystery_boxes"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", "day", name="uq_mystery_boxes_family_user_day"),
        CheckConstraint("kind IS NULL OR kind IN ('surprise','points')", name="ck_mystery_boxes_kind"),
        # Opened ⇔ the content is decided.
        CheckConstraint("(opened_at IS NULL) = (kind IS NULL)", name="ck_mystery_boxes_opened_iff_kind"),
        CheckConstraint("points >= 0", name="ck_mystery_boxes_points"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Date, nullable=False)                                # the perfect day (family timezone)
    kind = Column(String(16), nullable=True)                          # surprise | points, once opened
    surprise_id = Column(UUID(as_uuid=True), ForeignKey("mystery_surprises.id", ondelete="SET NULL"), nullable=True)
    surprise_title = Column(String(60), nullable=True)                # copied at opening
    surprise_emoji = Column(String(4), nullable=True)
    points = Column(Integer, nullable=False, default=0, server_default="0")
    opened_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)     # surprises only: a parent handed it over
    delivered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
```

(`Boolean` is unused — drop it from the import.)

Migration `2026_10_03_mystery_box.py`:

```python
"""mystery_surprises + mystery_boxes + families.mystery_box_points (UX-D4b)

Revision ID: mystery_box
Revises: teen_checkins
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "mystery_box"
down_revision = "teen_checkins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("mystery_box_points", sa.Integer(), nullable=True, server_default="20"),
    )
    # Families that already exist start UNDECIDED (NULL = boxes off + a
    # one-time opt-in card on the parent hub). Only families created after
    # this migration get the default of 20 (the quest's opt-in trick).
    op.execute("UPDATE families SET mystery_box_points = NULL")
    op.create_table(
        "mystery_surprises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(60), nullable=False),
        sa.Column("emoji", sa.String(4), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mystery_surprises_family_id", "mystery_surprises", ["family_id"])
    op.create_table(
        "mystery_boxes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("surprise_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mystery_surprises.id", ondelete="SET NULL"), nullable=True),
        sa.Column("surprise_title", sa.String(60), nullable=True),
        sa.Column("surprise_emoji", sa.String(4), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "user_id", "day", name="uq_mystery_boxes_family_user_day"),
        sa.CheckConstraint("kind IS NULL OR kind IN ('surprise','points')", name="ck_mystery_boxes_kind"),
        sa.CheckConstraint("(opened_at IS NULL) = (kind IS NULL)", name="ck_mystery_boxes_opened_iff_kind"),
        sa.CheckConstraint("points >= 0", name="ck_mystery_boxes_points"),
    )
    op.create_index("ix_mystery_boxes_family_id", "mystery_boxes", ["family_id"])
    op.create_index("ix_mystery_boxes_user_id", "mystery_boxes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mystery_boxes_user_id", table_name="mystery_boxes")
    op.drop_index("ix_mystery_boxes_family_id", table_name="mystery_boxes")
    op.drop_table("mystery_boxes")
    op.drop_index("ix_mystery_surprises_family_id", table_name="mystery_surprises")
    op.drop_table("mystery_surprises")
    op.drop_column("families", "mystery_box_points")
```

`models/__init__.py`: `from app.models.mystery import MysteryBox, MysterySurprise` next to `TeenCheckin`; add both names to `__all__`.

`models/family.py`, after `teen_checkin_decided_at`:

```python
    # UX-D4b mystery box: points maximum for the fallback bonus. NULL = an
    # existing family that has not decided (boxes off; one-time parent-hub
    # card), 0 = off by choice, > 0 = on. New families default to 20.
    mystery_box_points = Column(Integer, nullable=True, default=20, server_default="20")
```

`schemas/family.py` — `FamilyUpdate`: `mystery_box_points: Optional[int] = Field(None, ge=0, le=500)` (comment: `# UX-D4b mystery box points maximum; 0 switches boxes off.`); `FamilyResponse`: `mystery_box_points: Optional[int] = None`.

`family_export_service.py`: import `MysteryBox, MysterySurprise`; add both to `EXPORTED_FAMILY_TABLES` next to `TeenCheckin`; next to `quests = …` add `mystery_surprises = await _rows(db, fam(MysterySurprise))` and `mystery_boxes = await _rows(db, fam(MysteryBox))`; next to `"progress/quests.json"` add `"progress/mystery_surprises.json": _dump(mystery_surprises),` and `"progress/mystery_boxes.json": _dump(mystery_boxes),`.

- [ ] **Step 4: Run** `pytest tests/test_mystery_model.py tests/test_family_delete_export.py tests/test_quest_model.py` — PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) remove the `UPDATE … NULL` line from the migration: `test_existing_families_start_undecided…` fails. (b) drop `ck_mystery_boxes_opened_iff_kind` from the model: the `kind="points", points=12` case fails. Restore each.

- [ ] **Step 6: Commit** `feat(ux-d4b): mystery box tables, family setting, export`

---

### Task 2: Rules and service

**Files:**
- Create: `backend/app/services/mystery_service.py`
- Test: `backend/tests/test_mystery_rules.py`, `backend/tests/test_mystery_service.py`

**Interfaces:**
- Consumes: Task 1 models; `ProgressService.family_today / day_states`, `DayState`, `KID_ROLES`; `PointsService._get_user_locked`; `PointTransaction`, `TransactionType.BONUS`.
- Produces (`app.services.mystery_service`):
  - `JAR_MAX = 20`, `TITLE_MAX = 60`
  - `points_for(max_points: int, rng: random.Random) -> int`
  - `pick_surprise(surprises: list[MysterySurprise], last_surprise_id: Optional[UUID], rng: random.Random) -> Optional[MysterySurprise]`
  - `MysteryService.sync(db, user) -> MysteryResponse` (creates today's box on a perfect day)
  - `MysteryService.open(db, user, box_id) -> MysteryBoxView` (raises `NotFoundException` / `MysteryBoxesOff`)
  - `MysteryService.deliveries(db, family_id) -> list[DeliveryView]`
  - `MysteryService.mark_delivered(db, parent, box_id) -> None` (raises `NotFoundException`)
  - `MysteryService.list_surprises(db, family_id) -> list[MysterySurprise]`, `add_surprise(db, parent, title, emoji) -> MysterySurprise` (raises `ValidationError` on a full jar / bad title), `remove_surprise(db, family_id, surprise_id) -> None` (raises `NotFoundException`)
  - `class MysteryBoxesOff(Exception)`
  - Schemas (Task 3 adds them to `schemas/progress.py`; the service imports them): `MysteryBoxView(id, day, opened, kind, surprise_title, surprise_emoji, points)`, `MysteryResponse(applies, enabled, unopened: list[MysteryBoxView], opened_today: Optional[MysteryBoxView])`, `DeliveryView(id, kid_name, surprise_title, surprise_emoji, day, opened_at)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mystery_rules.py`:

```python
"""UX-D4b pure rules: the points fallback and the jar pick."""
import random
from uuid import uuid4

import pytest

from app.models.mystery import MysterySurprise
from app.services.mystery_service import JAR_MAX, TITLE_MAX, pick_surprise, points_for


def surprise(title="x"):
    return MysterySurprise(id=uuid4(), family_id=uuid4(), title=title)


def test_constants():
    assert (JAR_MAX, TITLE_MAX) == (20, 60)


class TestPoints:
    @pytest.mark.parametrize("maximum,lo", [(20, 5), (10, 2), (4, 1), (3, 1), (1, 1), (500, 125)])
    def test_between_a_quarter_and_the_maximum(self, maximum, lo):
        rng = random.Random(7)
        seen = {points_for(maximum, rng) for _ in range(400)}
        assert min(seen) >= lo and max(seen) <= maximum
        if maximum - lo < 50:                      # small ranges: both ends must come up
            assert lo in seen and maximum in seen

    def test_never_zero(self):
        assert points_for(1, random.Random(1)) == 1
        assert points_for(0, random.Random(1)) == 1


class TestPick:
    def test_nothing_from_an_empty_jar(self):
        assert pick_surprise([], None, random.Random(1)) is None

    def test_never_the_last_one_when_the_jar_has_two_or_more(self):
        a, b, c = surprise("a"), surprise("b"), surprise("c")
        rng = random.Random(3)
        for _ in range(100):
            assert pick_surprise([a, b, c], a.id, rng) is not a

    def test_the_only_one_is_allowed_again(self):
        only = surprise("only")
        assert pick_surprise([only], only.id, random.Random(1)) is only

    def test_every_eligible_surprise_can_come_up(self):
        items = [surprise(str(i)) for i in range(4)]
        rng = random.Random(11)
        picked = {pick_surprise(items, items[0].id, rng).id for _ in range(300)}
        assert picked == {s.id for s in items[1:]}
```

`tests/test_mystery_service.py`:

```python
"""UX-D4b mystery box against the test DB: created on a perfect day, opened once, delivered."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.exceptions import NotFoundException, ValidationError
from app.models.family import Family
from app.models.mystery import MysteryBox, MysterySurprise
from app.models.point_transaction import PointTransaction, TransactionType as PT
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import User, UserRole
from app.services.mystery_service import MysteryBoxesOff, MysteryService
from app.services.progress_service import ProgressService


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


async def _template(db, family_id, *, bonus=False):
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                     is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, kid, template, day, status=AssignmentStatus.COMPLETED, *, grade=None, approval=ApprovalStatus.NONE):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=kid.id, status=status,
                       approval_status=approval, completion_grade=grade, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _perfect_day(db, kid, *, chores=2):
    today = await _today(db, kid.family_id)
    chore = await _template(db, kid.family_id)
    for _ in range(chores):
        await _assign(db, kid, chore, today)
    return today, chore


async def _jar(db, family, parent, *titles):
    out = []
    for t in titles:
        out.append(await MysteryService.add_surprise(db, parent, t, "🎉"))
    return out


async def _boxes(db, kid=None):
    q = select(MysteryBox)
    if kid is not None:
        q = q.where(MysteryBox.user_id == kid.id)
    return list((await db.execute(q.order_by(MysteryBox.day))).scalars().all())


async def _bonus_rows(db, kid):
    return list((await db.execute(
        select(PointTransaction).where(PointTransaction.user_id == kid.id, PointTransaction.type == PT.BONUS)
    )).scalars().all())


class TestCreation:
    async def test_a_perfect_day_creates_one_closed_box(self, db_session, test_family, test_child_user):
        today, _ = await _perfect_day(db_session, test_child_user)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.applies is True and resp.enabled is True
        assert len(resp.unopened) == 1 and resp.unopened[0].day == today and resp.unopened[0].opened is False
        assert resp.opened_today is None
        again = await MysteryService.sync(db_session, test_child_user)
        assert [b.id for b in again.unopened] == [resp.unopened[0].id]
        assert len(await _boxes(db_session)) == 1

    async def test_an_unfinished_day_gives_no_box(self, db_session, test_family, test_child_user):
        today, chore = await _perfect_day(db_session, test_child_user)
        await _assign(db_session, test_child_user, chore, today, AssignmentStatus.PENDING)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.unopened == [] and await _boxes(db_session) == []

    async def test_no_chores_or_bonus_only_gives_no_box(self, db_session, test_family, test_child_user):
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []
        today = await _today(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        await _assign(db_session, test_child_user, bonus, today)
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []
        assert await _boxes(db_session) == []

    async def test_a_chore_awaiting_review_still_counts(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today, approval=ApprovalStatus.PENDING)
        assert len((await MysteryService.sync(db_session, test_child_user)).unopened) == 1

    async def test_a_rejected_or_missed_chore_spoils_the_day(self, db_session, test_family, test_child_user):
        today, chore = await _perfect_day(db_session, test_child_user)
        await _assign(db_session, test_child_user, chore, today, grade="missed")
        assert (await MysteryService.sync(db_session, test_child_user)).unopened == []

    async def test_off_and_undecided_families_get_nothing(self, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        for value in (0, None):
            test_family.mystery_box_points = value
            await db_session.commit()
            resp = await MysteryService.sync(db_session, test_child_user)
            assert resp.applies is True and resp.enabled is False and resp.unopened == []
        assert await _boxes(db_session) == []

    async def test_parents_do_not_apply(self, db_session, test_family, test_parent_user):
        await _perfect_day(db_session, test_parent_user)
        resp = await MysteryService.sync(db_session, test_parent_user)
        assert resp.applies is False and await _boxes(db_session) == []

    async def test_yesterdays_unopened_box_still_waits(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add(MysteryBox(family_id=test_family.id, user_id=test_child_user.id, day=today - timedelta(days=1),
                                  points=0, created_at=datetime.now(timezone.utc)))
        await db_session.commit()
        await _perfect_day(db_session, test_child_user)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert [b.day for b in resp.unopened] == [today - timedelta(days=1), today]


class TestOpening:
    async def _closed(self, db, kid):
        await _perfect_day(db, kid)
        return (await MysteryService.sync(db, kid)).unopened[0]

    async def test_an_empty_jar_pays_points_once(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert view.opened is True and view.kind == "points" and 5 <= view.points <= 20
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + view.points
        rows = await _bonus_rows(db_session, test_child_user)
        assert len(rows) == 1 and rows[0].points == view.points and rows[0].description == "Mystery box"
        again = await MysteryService.open(db_session, test_child_user, box.id)
        assert (again.kind, again.points) == (view.kind, view.points)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + view.points             # paid once
        assert len(await _bonus_rows(db_session, test_child_user)) == 1

    async def test_the_points_follow_the_family_maximum_and_language(self, db_session, test_family, test_child_user):
        test_family.mystery_box_points = 4
        test_child_user.preferred_lang = "es"
        await db_session.commit()
        box = await self._closed(db_session, test_child_user)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert 1 <= view.points <= 4
        assert (await _bonus_rows(db_session, test_child_user))[0].description == "Caja sorpresa"

    async def test_a_jar_surprise_is_copied_and_pays_nothing(self, db_session, test_family, test_parent_user, test_child_user):
        (dessert,) = await _jar(db_session, test_family, test_parent_user, "Pick dessert tonight")
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert (view.kind, view.surprise_title, view.surprise_emoji, view.points) == ("surprise", "Pick dessert tonight", "🎉", 0)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before and await _bonus_rows(db_session, test_child_user) == []
        row = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert row.surprise_id == dessert.id
        await MysteryService.remove_surprise(db_session, test_family.id, dessert.id)
        db_session.expire_all()
        row = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert row.surprise_title == "Pick dessert tonight" and row.surprise_id is None

    async def test_never_yesterdays_surprise(self, db_session, test_family, test_parent_user, test_child_user):
        a, b = await _jar(db_session, test_family, test_parent_user, "A", "B")
        today = await _today(db_session, test_family.id)
        db_session.add(MysteryBox(family_id=test_family.id, user_id=test_child_user.id, day=today - timedelta(days=1),
                                  kind="surprise", surprise_id=a.id, surprise_title="A", points=0,
                                  opened_at=datetime.now(timezone.utc) - timedelta(days=1),
                                  created_at=datetime.now(timezone.utc) - timedelta(days=1)))
        await db_session.commit()
        box = await self._closed(db_session, test_child_user)
        for _ in range(5):
            view = await MysteryService.open(db_session, test_child_user, box.id)
            assert view.surprise_title == "B"

    async def test_the_content_is_decided_at_opening(self, db_session, test_family, test_parent_user, test_child_user):
        box = await self._closed(db_session, test_child_user)                 # jar empty when the box appeared
        await _jar(db_session, test_family, test_parent_user, "Movie night")
        view = await MysteryService.open(db_session, test_child_user, box.id)
        assert view.kind == "surprise" and view.surprise_title == "Movie night"

    async def test_two_opens_at_once_pay_once(self, db_session, test_family, test_child_user, test_engine):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        box = await self._closed(db_session, test_child_user)
        before = int(test_child_user.points)
        factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

        async def one():
            async with factory() as s:
                kid = (await s.execute(select(User).where(User.id == test_child_user.id))).scalar_one()
                return await MysteryService.open(s, kid, box.id)

        a, b = await asyncio.gather(one(), one())
        assert (a.kind, a.points) == (b.kind, b.points)
        await db_session.refresh(test_child_user)
        assert test_child_user.points == before + a.points
        assert len(await _bonus_rows(db_session, test_child_user)) == 1

    async def test_only_the_owner_can_open(self, db_session, test_family, test_child_user, test_teen_user):
        box = await self._closed(db_session, test_child_user)
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, test_teen_user, box.id)
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, test_child_user, uuid4())
        assert (await _boxes(db_session))[0].opened_at is None

    async def test_another_family_cannot_open_it(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        other = Family(name="Other", mystery_box_points=20)
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="stranger@test.com", password_hash="x", name="S", role=UserRole.CHILD, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await MysteryService.open(db_session, stranger, box.id)

    async def test_a_family_that_switched_off_cannot_open_until_it_is_on_again(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        test_family.mystery_box_points = 0
        await db_session.commit()
        with pytest.raises(MysteryBoxesOff):
            await MysteryService.open(db_session, test_child_user, box.id)
        assert (await _boxes(db_session))[0].opened_at is None
        test_family.mystery_box_points = 20
        await db_session.commit()
        assert (await MysteryService.open(db_session, test_child_user, box.id)).opened is True

    async def test_sync_reports_todays_opened_box(self, db_session, test_family, test_child_user):
        box = await self._closed(db_session, test_child_user)
        await MysteryService.open(db_session, test_child_user, box.id)
        resp = await MysteryService.sync(db_session, test_child_user)
        assert resp.unopened == [] and resp.opened_today is not None and resp.opened_today.id == box.id


class TestDeliveries:
    async def test_surprises_wait_for_a_parent_and_points_do_not(self, db_session, test_family, test_parent_user, test_child_user, test_teen_user):
        await _jar(db_session, test_family, test_parent_user, "Pick dessert tonight")
        await _perfect_day(db_session, test_child_user)
        box = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, box.id)
        await MysteryService.remove_surprise(db_session, test_family.id,
                                             (await MysteryService.list_surprises(db_session, test_family.id))[0].id)
        await _perfect_day(db_session, test_teen_user)
        teen_box = (await MysteryService.sync(db_session, test_teen_user)).unopened[0]
        await MysteryService.open(db_session, test_teen_user, teen_box.id)         # empty jar → points
        rows = await MysteryService.deliveries(db_session, test_family.id)
        assert [(r.kid_name, r.surprise_title) for r in rows] == [("Test Child", "Pick dessert tonight")]
        await MysteryService.mark_delivered(db_session, test_parent_user, box.id)
        assert await MysteryService.deliveries(db_session, test_family.id) == []
        row = (await db_session.execute(select(MysteryBox).where(MysteryBox.id == box.id))).scalar_one()
        assert row.delivered_at is not None and row.delivered_by == test_parent_user.id

    async def test_another_familys_parent_cannot_mark_it(self, db_session, test_family, test_parent_user, test_child_user):
        await _jar(db_session, test_family, test_parent_user, "X")
        await _perfect_day(db_session, test_child_user)
        box = (await MysteryService.sync(db_session, test_child_user)).unopened[0]
        await MysteryService.open(db_session, test_child_user, box.id)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        stranger = User(email="op@test.com", password_hash="x", name="P", role=UserRole.PARENT, family_id=other.id,
                        email_verified=True, points=0)
        db_session.add(stranger)
        await db_session.commit()
        with pytest.raises(NotFoundException):
            await MysteryService.mark_delivered(db_session, stranger, box.id)
        assert len(await MysteryService.deliveries(db_session, test_family.id)) == 1


class TestJar:
    async def test_add_list_remove_scoped_to_the_family(self, db_session, test_family, test_parent_user):
        s = await MysteryService.add_surprise(db_session, test_parent_user, "  Pick dessert tonight  ", "🍨")
        assert (s.title, s.emoji, s.created_by) == ("Pick dessert tonight", "🍨", test_parent_user.id)
        other = Family(name="Other")
        db_session.add(other)
        await db_session.commit()
        db_session.add(MysterySurprise(family_id=other.id, title="Theirs", created_at=datetime.now(timezone.utc)))
        await db_session.commit()
        assert [x.title for x in await MysteryService.list_surprises(db_session, test_family.id)] == ["Pick dessert tonight"]
        with pytest.raises(NotFoundException):
            await MysteryService.remove_surprise(db_session, other.id, s.id)
        await MysteryService.remove_surprise(db_session, test_family.id, s.id)
        assert await MysteryService.list_surprises(db_session, test_family.id) == []

    async def test_limits(self, db_session, test_family, test_parent_user):
        for bad in ("", "   ", "x" * 61):
            with pytest.raises(ValidationError):
                await MysteryService.add_surprise(db_session, test_parent_user, bad, None)
        with pytest.raises(ValidationError):
            await MysteryService.add_surprise(db_session, test_parent_user, "ok", "🎉🎉🎉🎉🎉")   # > 4 code points
        for i in range(20):
            await MysteryService.add_surprise(db_session, test_parent_user, f"s{i}", None)
        with pytest.raises(ValidationError):
            await MysteryService.add_surprise(db_session, test_parent_user, "one too many", None)
        assert (await db_session.execute(select(func.count()).select_from(MysterySurprise))).scalar() == 20
```

- [ ] **Step 2: Run** both files — Expected: FAIL at import.

- [ ] **Step 3: Implement** — first the schemas (in `backend/app/schemas/progress.py`, appended):

```python
# ── UX-D4b mystery box ─────────────────────────────────────────────────
class MysteryBoxView(BaseModel):
    id: UUID
    day: date
    opened: bool
    kind: Optional[str] = None            # surprise | points once opened
    surprise_title: Optional[str] = None
    surprise_emoji: Optional[str] = None
    points: int = 0


class MysteryResponse(BaseModel):
    applies: bool
    enabled: bool = False                 # the family's boxes are on
    unopened: List[MysteryBoxView] = []   # oldest first
    opened_today: Optional[MysteryBoxView] = None


class DeliveryView(BaseModel):
    id: UUID
    kid_name: str
    surprise_title: str
    surprise_emoji: Optional[str] = None
    day: date
    opened_at: datetime


class SurpriseView(BaseModel):
    id: UUID
    title: str
    emoji: Optional[str] = None


class SurpriseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)   # trimmed and bounded to 60 by the service
    emoji: Optional[str] = Field(None, max_length=8)
```

(Make sure `List`, `datetime`, `Field` are imported at the top of that module.)

`backend/app/services/mystery_service.py`:

```python
"""UX-D4b mystery box: a perfect day earns a closed box; opening it reveals a
surprise from the parents' jar, or a points bonus when the jar is empty.

Created on read (the badge/quest pattern) and paid once at opening through a
guarded UPDATE. Pure rules first, then the family-scoped queries.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ValidationError
from app.models.family import Family
from app.models.mystery import MysteryBox, MysterySurprise
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.user import User, UserRole
from app.schemas.progress import DeliveryView, MysteryBoxView, MysteryResponse
from app.services.points_service import PointsService
from app.services.progress_service import KID_ROLES, DayState, ProgressService, compute_streak

JAR_MAX = 20      # surprises per family
TITLE_MAX = 60
EMOJI_MAX = 4


class MysteryBoxesOff(Exception):
    """The family's boxes are off (0 or undecided): the box waits, unopened."""


def points_for(max_points: int, rng: random.Random) -> int:
    """A whole number from a quarter of the maximum up to the maximum, never 0."""
    m = max(1, int(max_points or 0))
    return rng.randint(max(1, m // 4), m)


def pick_surprise(
    surprises: list[MysterySurprise], last_surprise_id: Optional[UUID], rng: random.Random,
) -> Optional[MysterySurprise]:
    """A random surprise, never the kid's most recent one when there is a choice."""
    if not surprises:
        return None
    pool = [s for s in surprises if s.id != last_surprise_id] or list(surprises)
    return rng.choice(pool)


def _view(box: MysteryBox) -> MysteryBoxView:
    return MysteryBoxView(
        id=box.id, day=box.day, opened=box.opened_at is not None, kind=box.kind,
        surprise_title=box.surprise_title, surprise_emoji=box.surprise_emoji, points=int(box.points or 0),
    )


# ── Queries (family-scoped) ──────────────────────────────────────────────
class MysteryService:
    @staticmethod
    async def _max_points(db: AsyncSession, family_id: UUID) -> int:
        return int((await db.execute(select(Family.mystery_box_points).where(Family.id == family_id))).scalar() or 0)

    @staticmethod
    async def sync(db: AsyncSession, user: User) -> MysteryResponse:
        """Create today's closed box when the day is perfect (idempotent), then
        report the kid's unopened boxes and today's opened one."""
        if user.role not in KID_ROLES:
            return MysteryResponse(applies=False)
        family_id, user_id = user.family_id, user.id
        maximum = await MysteryService._max_points(db, family_id)
        if maximum <= 0:
            return MysteryResponse(applies=True, enabled=False)
        today, tz = await ProgressService.family_today(db, family_id)
        states = await ProgressService.day_states(db, family_id, user_id, today, tz)
        if states.get(today) == DayState.done:
            await db.execute(
                pg_insert(MysteryBox)
                .values(family_id=family_id, user_id=user_id, day=today, points=0,
                        created_at=datetime.now(timezone.utc))
                .on_conflict_do_nothing(constraint="uq_mystery_boxes_family_user_day")
            )
            await db.commit()
        rows = (await db.execute(
            select(MysteryBox).where(
                MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
                (MysteryBox.opened_at.is_(None)) | (MysteryBox.day == today),
            ).order_by(MysteryBox.day)
        )).scalars().all()
        unopened = [_view(b) for b in rows if b.opened_at is None]
        opened_today = next((_view(b) for b in rows if b.opened_at is not None and b.day == today), None)
        return MysteryResponse(applies=True, enabled=True, unopened=unopened, opened_today=opened_today)

    @staticmethod
    async def open(db: AsyncSession, user: User, box_id: UUID, rng: Optional[random.Random] = None) -> MysteryBoxView:
        """Decide and pay the box's content exactly once. The guarded UPDATE is
        the gate: of two openers, the second waits on the row lock, matches
        nothing, and reads what the first one revealed."""
        rng = rng or random.Random()
        family_id, user_id = user.family_id, user.id
        box = (await db.execute(
            select(MysteryBox).where(
                MysteryBox.id == box_id, MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
            )
        )).scalar_one_or_none()
        if box is None:
            raise NotFoundException("Box not found")
        if box.opened_at is not None:
            return _view(box)
        maximum = await MysteryService._max_points(db, family_id)
        if maximum <= 0:
            raise MysteryBoxesOff()

        jar = await MysteryService.list_surprises(db, family_id)
        last = (await db.execute(
            select(MysteryBox.surprise_id).where(
                MysteryBox.family_id == family_id, MysteryBox.user_id == user_id,
                MysteryBox.opened_at.is_not(None), MysteryBox.id != box_id,
            ).order_by(MysteryBox.opened_at.desc()).limit(1)
        )).scalar()
        surprise = pick_surprise(jar, last, rng)
        values = dict(opened_at=datetime.now(timezone.utc))
        if surprise is not None:
            values.update(kind="surprise", surprise_id=surprise.id, surprise_title=surprise.title,
                          surprise_emoji=surprise.emoji, points=0)
        else:
            values.update(kind="points", points=points_for(maximum, rng))
        opened = (await db.execute(
            update(MysteryBox)
            .where(MysteryBox.id == box_id, MysteryBox.opened_at.is_(None))
            .values(**values)
            .returning(MysteryBox.id)
            .execution_options(synchronize_session=False)
        )).first()
        if opened is not None and values["kind"] == "points":
            kid = await PointsService._get_user_locked(db, user_id, family_id)
            await db.refresh(kid)                      # identity map may hold the auth-time balance
            before = int(kid.points or 0)
            kid.points = before + values["points"]
            lang = (user.preferred_lang or "en").lower()
            db.add(PointTransaction(
                type=TransactionType.BONUS, user_id=kid.id, family_id=family_id, points=values["points"],
                balance_before=before, balance_after=kid.points,
                description="Caja sorpresa" if lang.startswith("es") else "Mystery box",
            ))
        await db.commit()
        await db.refresh(box)
        return _view(box)

    @staticmethod
    async def deliveries(db: AsyncSession, family_id: UUID) -> list[DeliveryView]:
        rows = (await db.execute(
            select(MysteryBox, User.name)
            .join(User, User.id == MysteryBox.user_id)
            .where(MysteryBox.family_id == family_id, MysteryBox.kind == "surprise", MysteryBox.delivered_at.is_(None))
            .order_by(MysteryBox.opened_at.desc())
        )).all()
        return [
            DeliveryView(id=b.id, kid_name=name, surprise_title=b.surprise_title or "", surprise_emoji=b.surprise_emoji,
                         day=b.day, opened_at=b.opened_at)
            for b, name in rows
        ]

    @staticmethod
    async def mark_delivered(db: AsyncSession, parent: User, box_id: UUID) -> None:
        done = (await db.execute(
            update(MysteryBox)
            .where(MysteryBox.id == box_id, MysteryBox.family_id == parent.family_id,
                   MysteryBox.kind == "surprise", MysteryBox.delivered_at.is_(None))
            .values(delivered_at=datetime.now(timezone.utc), delivered_by=parent.id)
            .returning(MysteryBox.id)
            .execution_options(synchronize_session=False)
        )).first()
        if done is None:
            raise NotFoundException("Nothing to deliver")
        await db.commit()

    # ── the jar ─────────────────────────────────────────────────────────
    @staticmethod
    async def list_surprises(db: AsyncSession, family_id: UUID) -> list[MysterySurprise]:
        return list((await db.execute(
            select(MysterySurprise).where(MysterySurprise.family_id == family_id).order_by(MysterySurprise.created_at)
        )).scalars().all())

    @staticmethod
    async def add_surprise(db: AsyncSession, parent: User, title: str, emoji: Optional[str]) -> MysterySurprise:
        clean = " ".join((title or "").split())
        if not clean or len(clean) > TITLE_MAX:
            raise ValidationError(f"A surprise is 1 to {TITLE_MAX} characters")
        icon = (emoji or "").strip() or None
        if icon is not None and len(icon) > EMOJI_MAX:
            raise ValidationError("One emoji at most")
        count = (await db.execute(
            select(func.count()).select_from(MysterySurprise).where(MysterySurprise.family_id == parent.family_id)
        )).scalar() or 0
        if count >= JAR_MAX:
            raise ValidationError(f"The jar holds {JAR_MAX} surprises at most")
        row = MysterySurprise(family_id=parent.family_id, title=clean, emoji=icon, created_by=parent.id,
                              created_at=datetime.now(timezone.utc))
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @staticmethod
    async def remove_surprise(db: AsyncSession, family_id: UUID, surprise_id: UUID) -> None:
        row = (await db.execute(
            select(MysterySurprise).where(MysterySurprise.id == surprise_id, MysterySurprise.family_id == family_id)
        )).scalar_one_or_none()
        if row is None:
            raise NotFoundException("Surprise not found")
        await db.delete(row)
        await db.commit()
```

(`compute_streak` is unused — drop it from the import. `KID_ROLES`, `DayState`, `ProgressService` are used.)

- [ ] **Step 4: Run** `pytest tests/test_mystery_rules.py tests/test_mystery_service.py tests/test_mystery_model.py` — PASS. If `test_two_opens_at_once_pay_once` cannot use the `test_engine` fixture as written, read `tests/conftest.py` for the engine fixture's real name and adjust the test, not the service. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) remove `MysteryBox.opened_at.is_(None)` from the guarded UPDATE's `where`: `test_an_empty_jar_pays_points_once` fails. (b) remove `MysteryBox.user_id == user_id` from `open`'s select: `test_only_the_owner_can_open` fails. (c) `if maximum <= 0: raise MysteryBoxesOff()` → `pass`: `test_a_family_that_switched_off…` fails. (d) `pool = … or list(surprises)` → `pool = list(surprises)`: `test_never_yesterdays_surprise` fails. (e) `states.get(today) == DayState.done` → `in states`: `test_an_unfinished_day_gives_no_box` fails. Restore each.

- [ ] **Step 6: Commit** `feat(ux-d4b): mystery box rules and service`

---

### Task 3: Routes

**Files:**
- Modify: `backend/app/api/routes/progress.py`, `backend/app/api/routes/families.py`
- Test: `backend/tests/test_mystery_api.py`

**Interfaces:**
- Produces: `GET /api/progress/mystery` → `MysteryResponse`; `POST /api/progress/mystery/{id}/open` → `MysteryBoxView` (404 / 409); `GET /api/progress/mystery/deliveries` → `list[DeliveryView]` (parent); `POST /api/progress/mystery/{id}/delivered` → 204 (parent); `GET /api/families/surprises` → `list[SurpriseView]`, `POST /api/families/surprises` → `SurpriseView` (201; 400 on limits), `DELETE /api/families/surprises/{id}` → 204 (parent).

- [ ] **Step 1: Write the failing tests**

```python
"""UX-D4b mystery box endpoints."""
from datetime import timedelta
from uuid import uuid4

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.services.progress_service import ProgressService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _perfect_day(db, kid):
    today, _tz = await ProgressService.family_today(db, kid.family_id)
    t = TaskTemplate(id=uuid4(), title="Chore", points=10, interval_days=1, assignment_type=AssignmentType.AUTO,
                     is_bonus=False, is_active=True, family_id=kid.family_id)
    db.add(t)
    await db.commit()
    db.add(TaskAssignment(family_id=kid.family_id, template_id=t.id, assigned_to=kid.id, status=AssignmentStatus.COMPLETED,
                          approval_status=ApprovalStatus.NONE, assigned_date=today,
                          week_of=today - timedelta(days=today.weekday())))
    await db.commit()


class TestKid:
    async def test_requires_auth(self, client):
        assert (await client.get("/api/progress/mystery")).status_code in (401, 403)

    async def test_a_perfect_day_shows_a_box_and_it_opens_once(self, client, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        r = await client.get("/api/progress/mystery", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["applies"] is True and body["enabled"] is True and len(body["unopened"]) == 1
        box_id = body["unopened"][0]["id"]
        o = await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)
        assert o.status_code == 200 and o.json()["kind"] == "points" and 5 <= o.json()["points"] <= 20
        again = await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)
        assert again.json() == o.json()
        after = (await client.get("/api/progress/mystery", headers=h)).json()
        assert after["unopened"] == [] and after["opened_today"]["id"] == box_id

    async def test_someone_elses_box_is_not_found(self, client, db_session, test_family, test_child_user, test_teen_user):
        await _perfect_day(db_session, test_child_user)
        box_id = (await client.get("/api/progress/mystery", headers=await _login(client, "child@test.com"))).json()["unopened"][0]["id"]
        r = await client.post(f"/api/progress/mystery/{box_id}/open", headers=await _login(client, "teen@test.com"))
        assert r.status_code == 404

    async def test_boxes_off_is_a_conflict(self, client, db_session, test_family, test_child_user):
        await _perfect_day(db_session, test_child_user)
        h = await _login(client, "child@test.com")
        box_id = (await client.get("/api/progress/mystery", headers=h)).json()["unopened"][0]["id"]
        test_family.mystery_box_points = 0
        await db_session.commit()
        assert (await client.post(f"/api/progress/mystery/{box_id}/open", headers=h)).status_code == 409
        assert (await client.get("/api/progress/mystery", headers=h)).json()["enabled"] is False

    async def test_a_parent_does_not_apply(self, client, test_parent_user, auth_headers):
        r = await client.get("/api/progress/mystery", headers=auth_headers)
        assert r.status_code == 200 and r.json() == {"applies": False, "enabled": False, "unopened": [], "opened_today": None}


class TestParent:
    async def test_jar_crud_and_deliveries(self, client, db_session, test_family, test_parent_user, test_child_user, auth_headers):
        assert (await client.get("/api/families/surprises", headers=auth_headers)).json() == []
        r = await client.post("/api/families/surprises", json={"title": " Pick dessert tonight ", "emoji": "🍨"}, headers=auth_headers)
        assert r.status_code == 201 and r.json()["title"] == "Pick dessert tonight" and r.json()["emoji"] == "🍨"
        sid = r.json()["id"]
        assert (await client.post("/api/families/surprises", json={"title": "   "}, headers=auth_headers)).status_code in (400, 422)
        assert (await client.post("/api/families/surprises", json={"title": "x" * 61}, headers=auth_headers)).status_code in (400, 422)
        await _perfect_day(db_session, test_child_user)
        kid = await _login(client, "child@test.com")
        box_id = (await client.get("/api/progress/mystery", headers=kid)).json()["unopened"][0]["id"]
        opened = (await client.post(f"/api/progress/mystery/{box_id}/open", headers=kid)).json()
        assert opened["kind"] == "surprise" and opened["surprise_title"] == "Pick dessert tonight"
        d = await client.get("/api/progress/mystery/deliveries", headers=auth_headers)
        assert d.status_code == 200 and [(x["kid_name"], x["surprise_title"]) for x in d.json()] == [("Test Child", "Pick dessert tonight")]
        assert (await client.post(f"/api/progress/mystery/{box_id}/delivered", headers=auth_headers)).status_code == 204
        assert (await client.get("/api/progress/mystery/deliveries", headers=auth_headers)).json() == []
        assert (await client.post(f"/api/progress/mystery/{box_id}/delivered", headers=auth_headers)).status_code == 404
        assert (await client.delete(f"/api/families/surprises/{sid}", headers=auth_headers)).status_code == 204
        assert (await client.delete(f"/api/families/surprises/{sid}", headers=auth_headers)).status_code == 404

    async def test_kids_cannot_touch_the_jar_or_deliveries(self, client, db_session, test_family, test_child_user):
        h = await _login(client, "child@test.com")
        assert (await client.get("/api/families/surprises", headers=h)).status_code in (401, 403)
        assert (await client.post("/api/families/surprises", json={"title": "x"}, headers=h)).status_code in (401, 403)
        assert (await client.get("/api/progress/mystery/deliveries", headers=h)).status_code in (401, 403, 404)
        assert (await client.post(f"/api/progress/mystery/{uuid4()}/delivered", headers=h)).status_code in (401, 403, 404)
```

- [ ] **Step 2: Run** `pytest tests/test_mystery_api.py` — Expected: FAIL (404s).

- [ ] **Step 3: Implement**

`routes/progress.py` — extend the schema import with `DeliveryView, MysteryBoxView, MysteryResponse`, import `require_parent_role`, `UUID`, `List`, and `from app.services.mystery_service import MysteryBoxesOff, MysteryService`; append:

```python
# ── UX-D4b mystery box ─────────────────────────────────────────────────
@router.get("/mystery", response_model=MysteryResponse)
async def my_mystery(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MysteryResponse:
    """The signed-in kid's boxes. This GET also creates today's box when the
    day is perfect (idempotent) — work on read, like badges and the quest."""
    return await MysteryService.sync(db, current_user)


@router.get("/mystery/deliveries", response_model=List[DeliveryView])
async def deliveries(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> List[DeliveryView]:
    """Surprises revealed by the family's kids that a parent has not handed over yet."""
    return await MysteryService.deliveries(db, current_user.family_id)


@router.post("/mystery/{box_id}/open", response_model=MysteryBoxView)
async def open_box(
    box_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MysteryBoxView:
    if current_user.role not in KID_ROLES:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        return await MysteryService.open(db, current_user, box_id)
    except MysteryBoxesOff:
        raise HTTPException(status_code=409, detail="Mystery boxes are off right now")


@router.post("/mystery/{box_id}/delivered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_delivered(
    box_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await MysteryService.mark_delivered(db, current_user, box_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

(`NotFoundException` is turned into a 404 by the app's exception handlers — confirm with `grep -n NotFoundException backend/app/main.py`; if it is not, catch it and raise `HTTPException(404)` in both kid routes.) Note the `/mystery/deliveries` route is declared BEFORE `/mystery/{box_id}/…` so it is never read as a box id.

`routes/families.py` — add `from app.schemas.progress import SurpriseCreate, SurpriseView` and `from app.services.mystery_service import MysteryService`; insert BEFORE the `@router.get("/{family_id}", …)` route (a literal path must come before the UUID catch-all):

```python
# ── UX-D4b mystery box: the surprise jar (parent only) ────────────────
@router.get("/surprises", response_model=List[SurpriseView])
async def list_surprises(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    rows = await MysteryService.list_surprises(db, to_uuid_required(current_user.family_id))
    return [SurpriseView(id=r.id, title=r.title, emoji=r.emoji) for r in rows]


@router.post("/surprises", response_model=SurpriseView, status_code=status.HTTP_201_CREATED)
async def add_surprise(
    data: SurpriseCreate,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    row = await MysteryService.add_surprise(db, current_user, data.title, data.emoji)
    return SurpriseView(id=row.id, title=row.title, emoji=row.emoji)


@router.delete("/surprises/{surprise_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_surprise(
    surprise_id: UUID,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    await MysteryService.remove_surprise(db, to_uuid_required(current_user.family_id), surprise_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run** `pytest tests/test_mystery_api.py tests/test_mystery_service.py tests/test_quest_api.py tests/test_families.py` (or whatever the families route test file is called — `ls backend/tests | grep -i famil`) — PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation check** — swap `require_parent_role` for `get_current_user` on `/surprises`: `test_kids_cannot_touch_the_jar_or_deliveries` fails. Restore.

- [ ] **Step 6: Commit** `feat(ux-d4b): mystery box and surprise jar endpoints`

---

### Task 4: Frontend — the kid card

**Files:**
- Create: `frontend/src/lib/mystery.ts`, `frontend/src/components/home/MysteryBoxCard.astro`
- Modify: `frontend/src/components/home/KidHome.astro`, `frontend/src/pages/dashboard.astro`
- Test: `frontend/test/mystery.test.ts`, `frontend/test/mystery-card.test.ts`

**Interfaces:**
- Consumes: `GET /api/progress/mystery`, `POST /api/progress/mystery/{id}/open`.
- Produces (`lib/mystery.ts`): `MYSTERY_COPY`, `type MysteryView = { closedCount: number; closedId: string | null; revealed: { kind: "surprise" | "points"; title: string; emoji: string; points: number } | null }`, `mysteryView(resp: unknown): MysteryView | null` (null unless `applies && enabled`), `mysteryDomUpdate(view, lang, starMode): { showClosed, closedLabel, showRevealed, revealedText }`, `revealedFrom(box: unknown)`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/mystery.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { MYSTERY_COPY, mysteryDomUpdate, mysteryView, revealedFrom } from "../src/lib/mystery";

const closed = (id: string, day = "2026-10-03") => ({ id, day, opened: false, kind: null, surprise_title: null, surprise_emoji: null, points: 0 });
const surprise = { id: "b2", day: "2026-10-03", opened: true, kind: "surprise", surprise_title: "Pick dessert tonight", surprise_emoji: "🍨", points: 0 };
const points = { id: "b3", day: "2026-10-03", opened: true, kind: "points", surprise_title: null, surprise_emoji: null, points: 12 };

describe("mysteryView", () => {
    it("is null unless the family's boxes are on for a kid", () => {
        for (const v of [null, undefined, {}, { applies: false }, { applies: true, enabled: false }, "x"]) {
            expect(mysteryView(v)).toBeNull();
        }
    });
    it("counts the closed boxes and keeps the oldest one's id", () => {
        const v = mysteryView({ applies: true, enabled: true, unopened: [closed("b1", "2026-10-02"), closed("b9")], opened_today: null });
        expect(v).toEqual({ closedCount: 2, closedId: "b1", revealed: null });
    });
    it("carries today's reveal when nothing is closed", () => {
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: surprise })).toEqual({
            closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Pick dessert tonight", emoji: "🍨", points: 0 },
        });
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: points })?.revealed).toEqual({ kind: "points", title: "", emoji: "", points: 12 });
    });
    it("an empty but enabled family still gets a view (so the card can wake up later)", () => {
        expect(mysteryView({ applies: true, enabled: true, unopened: [], opened_today: null })).toEqual({ closedCount: 0, closedId: null, revealed: null });
    });
});

describe("revealedFrom", () => {
    it("reads an opened box and rejects a closed one", () => {
        expect(revealedFrom(points)).toEqual({ kind: "points", title: "", emoji: "", points: 12 });
        expect(revealedFrom(closed("b1"))).toBeNull();
        expect(revealedFrom(null)).toBeNull();
    });
});

describe("mysteryDomUpdate", () => {
    it("closed: one box, or several with a count", () => {
        const one = mysteryDomUpdate({ closedCount: 1, closedId: "b1", revealed: null }, "en", false);
        expect(one).toMatchObject({ showClosed: true, showRevealed: false, closedLabel: "🎁 A mystery box! Tap to open" });
        const two = mysteryDomUpdate({ closedCount: 2, closedId: "b1", revealed: null }, "es", false);
        expect(two.closedLabel).toBe("🎁 ¡Una caja sorpresa! Toca para abrir ×2");
    });
    it("revealed surprise and points, with stars in star mode", () => {
        const s = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Pick dessert tonight", emoji: "🍨", points: 0 } }, "en", false);
        expect(s).toMatchObject({ showClosed: false, showRevealed: true, revealedText: "You got: Pick dessert tonight 🍨 — ask your parents!" });
        const es = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "surprise", title: "Postre", emoji: "", points: 0 } }, "es", false);
        expect(es.revealedText).toBe("Te tocó: Postre — ¡pídesela a tus papás!");
        const p = mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "points", title: "", emoji: "", points: 12 } }, "en", false);
        expect(p.revealedText).toBe("+12 points");
        expect(mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: { kind: "points", title: "", emoji: "", points: 12 } }, "es", true).revealedText).toBe("+12 ⭐");
    });
    it("nothing to show hides both blocks", () => {
        expect(mysteryDomUpdate({ closedCount: 0, closedId: null, revealed: null }, "en", false)).toMatchObject({ showClosed: false, showRevealed: false });
    });
    it("copy exists in both languages", () => {
        for (const key of ["closed", "opening", "off", "failed"] as const) {
            expect(MYSTERY_COPY[key].es.length).toBeGreaterThan(3);
            expect(MYSTERY_COPY[key].en.length).toBeGreaterThan(3);
        }
    });
});
```

`frontend/test/mystery-card.test.ts`:

```ts
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const card = read("../src/components/home/MysteryBoxCard.astro");
const home = read("../src/components/home/KidHome.astro");
const dash = read("../src/pages/dashboard.astro");

describe("MysteryBoxCard", () => {
    it("has the closed and revealed blocks, toggled with the hidden attribute, from the shared mapping", () => {
        expect(card).toMatch(/data-mystery-closed hidden=\{!u\.showClosed\}/);
        expect(card).toMatch(/data-mystery-revealed hidden=\{!u\.showRevealed\}/);
        expect(card).toMatch(/const u = mysteryDomUpdate\(view, lang, starMode\);/);
        expect(card).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("hides the whole card while there is nothing to show, and wakes up when the deck empties", () => {
        expect(card).toMatch(/<section data-mystery-card[^>]*hidden=\{!u\.showClosed && !u\.showRevealed\}/);
        expect(card).toContain('"ftm:deck-empty"');
        expect(card).toMatch(/fetch\("\/api\/progress\/mystery"/);
    });
    it("opens through the proxied route, celebrates once, and keeps busy state", () => {
        expect(card).toMatch(/fetch\(`\/api\/progress\/mystery\/\$\{id\}\/open`/);
        expect(card).toMatch(/method: "POST"/);
        expect(card).toContain("fireConfetti(");
        expect(card).toMatch(/if \(busy\) return;/);
        expect(card).toMatch(/showToast\(/);
        expect(card).toMatch(/r\.status === 409/);
        expect(existsSync(path("../src/pages/api/progress/[...path].ts"))).toBe(true);
    });
    it("uses no native dialog and no emoji in a heading 1", () => {
        expect(card).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(card).not.toMatch(/<h1/);
    });
});

describe("wiring", () => {
    it("the dashboard fetches the boxes and KidHome shows the card between the check-in and the quest", () => {
        expect(dash).toMatch(/apiFetch<any>\("\/api\/progress\/mystery", \{ token \}\)/);
        expect(dash).toMatch(/const mystery = mysteryView\(mysteryResp\);/);
        expect(dash).toMatch(/mystery=\{mystery\}/);
        const checkin = home.indexOf("<CheckinCard");
        const box = home.indexOf("<MysteryBoxCard");
        const quest = home.indexOf("<QuestCard");
        expect(box).toBeGreaterThan(checkin);
        expect(quest).toBeGreaterThan(box);
        expect(home).toMatch(/\{mystery && <MysteryBoxCard view=\{mystery\} lang=\{lang\} starMode=\{starMode\} \/>\}/);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/mystery.test.ts test/mystery-card.test.ts` — Expected: FAIL (cannot resolve `../src/lib/mystery`).

- [ ] **Step 3: Implement**

`frontend/src/lib/mystery.ts`:

```ts
/** UX-D4b mystery box — the only place its copy lives. Pure helpers: the
 *  server view → the card's state, and the exact strings the card writes. */

export type Lang = "es" | "en";

export const MYSTERY_COPY = {
    heading: { es: "Caja sorpresa", en: "Mystery box" },
    closed: { es: "🎁 ¡Una caja sorpresa! Toca para abrir", en: "🎁 A mystery box! Tap to open" },
    opening: { es: "Abriendo…", en: "Opening…" },
    off: { es: "Las cajas están apagadas por ahora.", en: "Boxes are off right now." },
    failed: { es: "No se pudo abrir. Intenta de nuevo.", en: "Could not open. Try again." },
} as const;

export type Revealed = { kind: "surprise" | "points"; title: string; emoji: string; points: number };
export type MysteryView = { closedCount: number; closedId: string | null; revealed: Revealed | null };

/** An opened box from the API, or null for anything else. */
export function revealedFrom(box: unknown): Revealed | null {
    const b = box as Record<string, unknown> | null;
    if (!b || b.opened !== true || (b.kind !== "surprise" && b.kind !== "points")) return null;
    return {
        kind: b.kind,
        title: typeof b.surprise_title === "string" ? b.surprise_title : "",
        emoji: typeof b.surprise_emoji === "string" ? b.surprise_emoji : "",
        points: typeof b.points === "number" ? b.points : 0,
    };
}

/** null unless the boxes apply to this user and are on for the family. An
 *  enabled family with nothing to show still gets a view: the card renders
 *  hidden and wakes up when the deck empties. */
export function mysteryView(resp: unknown): MysteryView | null {
    const r = resp as Record<string, unknown> | null;
    if (!r || r.applies !== true || r.enabled !== true) return null;
    const unopened = Array.isArray(r.unopened) ? (r.unopened as Array<Record<string, unknown>>) : [];
    const first = unopened[0];
    return {
        closedCount: unopened.length,
        closedId: first && typeof first.id === "string" ? first.id : null,
        revealed: unopened.length === 0 ? revealedFrom(r.opened_today) : null,
    };
}

export function mysteryDomUpdate(view: MysteryView, lang: Lang, starMode: boolean) {
    const showClosed = view.closedCount > 0;
    const showRevealed = !showClosed && view.revealed !== null;
    let revealedText = "";
    if (view.revealed) {
        if (view.revealed.kind === "points") {
            revealedText = starMode ? `+${view.revealed.points} ⭐` : lang === "es" ? `+${view.revealed.points} puntos` : `+${view.revealed.points} points`;
        } else {
            const what = [view.revealed.title, view.revealed.emoji].filter(Boolean).join(" ");
            revealedText = lang === "es" ? `Te tocó: ${what} — ¡pídesela a tus papás!` : `You got: ${what} — ask your parents!`;
        }
    }
    return {
        showClosed,
        closedLabel: showClosed ? `${MYSTERY_COPY.closed[lang]}${view.closedCount > 1 ? ` ×${view.closedCount}` : ""}` : "",
        showRevealed,
        revealedText,
    };
}
```

`frontend/src/components/home/MysteryBoxCard.astro`:

```astro
---
/**
 * UX-D4b mystery box on the kid home. One card: closed (tap to open) or
 * revealed (today's surprise / points). Rendered from mysteryDomUpdate(), the
 * same mapping the script writes back after an open or a refetch. Hidden
 * entirely while there is nothing to show, so it can wake up the moment the
 * last chore is done (ftm:deck-empty) without a reload.
 */
import { MYSTERY_COPY, mysteryDomUpdate, type MysteryView } from "../../lib/mystery";

interface Props {
    view: MysteryView;
    lang: "es" | "en";
    starMode: boolean;
}
const { view, lang, starMode } = Astro.props;
const u = mysteryDomUpdate(view, lang, starMode);
---

<section data-mystery-card data-lang={lang} data-star={starMode ? "1" : "0"} data-box-id={view.closedId ?? ""}
         hidden={!u.showClosed && !u.showRevealed}
         class="rounded-2xl border border-brand-ink/10 bg-white p-4 shadow-[var(--shadow-card)]">
    <h2 class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">{MYSTERY_COPY.heading[lang]}</h2>
    <button type="button" data-mystery-closed hidden={!u.showClosed}
            class="mt-2 w-full rounded-xl bg-brand-sun px-4 py-4 text-left font-display text-lg font-extrabold text-brand-ink transition-transform active:scale-95">
        <span data-mystery-closed-label>{u.closedLabel}</span>
    </button>
    <div data-mystery-revealed hidden={!u.showRevealed} class="mt-2 rounded-xl bg-brand-sun px-3 py-3 text-brand-ink">
        <p class="font-display text-lg font-extrabold" data-mystery-revealed-text>{u.revealedText}</p>
    </div>
</section>

<script>
    import { fireConfetti } from "../../lib/celebrate";
    import { MYSTERY_COPY, mysteryDomUpdate, mysteryView, revealedFrom, type MysteryView } from "../../lib/mystery";
    import { showToast } from "../../lib/toast";

    const card = document.querySelector<HTMLElement>("[data-mystery-card]");
    if (card) {
        const lang = card.dataset.lang === "en" ? "en" : "es";
        const star = card.dataset.star === "1";
        const closed = card.querySelector<HTMLButtonElement>("[data-mystery-closed]")!;
        const closedLabel = card.querySelector<HTMLElement>("[data-mystery-closed-label]")!;
        const revealed = card.querySelector<HTMLElement>("[data-mystery-revealed]")!;
        const revealedText = card.querySelector<HTMLElement>("[data-mystery-revealed-text]")!;
        let busy = false;

        const paint = (view: MysteryView) => {
            const u = mysteryDomUpdate(view, lang, star);
            card.dataset.boxId = view.closedId ?? "";
            closed.toggleAttribute("hidden", !u.showClosed);
            closedLabel.textContent = u.closedLabel;
            revealed.toggleAttribute("hidden", !u.showRevealed);
            revealedText.textContent = u.revealedText;
            card.toggleAttribute("hidden", !u.showClosed && !u.showRevealed);
        };

        const refresh = async () => {
            try {
                const r = await fetch("/api/progress/mystery", { credentials: "same-origin" });
                if (!r.ok) return;
                const view = mysteryView(await r.json());
                if (view) paint(view);
            } catch {
                /* keep what is shown */
            }
        };

        closed.addEventListener("click", async () => {
            if (busy) return;
            const id = card.dataset.boxId;
            if (!id) return;
            busy = true;
            closedLabel.textContent = MYSTERY_COPY.opening[lang];
            try {
                const r = await fetch(`/api/progress/mystery/${id}/open`, { method: "POST", credentials: "same-origin" });
                if (r.status === 409) {
                    showToast(MYSTERY_COPY.off[lang], "info");
                    await refresh();
                    return;
                }
                if (!r.ok) throw new Error(String(r.status));
                const got = revealedFrom(await r.json());
                if (!got) throw new Error("bad reveal");
                // Show this reveal first, then let the server say what else waits.
                paint({ closedCount: 0, closedId: null, revealed: got });
                fireConfetti(card);
                await refresh();
            } catch {
                showToast(MYSTERY_COPY.failed[lang], "error");
                await refresh();
            } finally {
                busy = false;
            }
        });

        // The deck fires this the moment the day's last chore is done.
        window.addEventListener("ftm:deck-empty", () => void refresh());
    }
</script>
```

Check `lib/celebrate.ts`'s `fireConfetti` signature (it takes an optional host element) and the `showToast` types (`"info"` must be a valid `ToastType`; it is). Note `refresh()` after a reveal: when the server still has unopened boxes it repaints to the closed state with the count — the spec's "×2" behaviour — so the kid sees the next box right away; the reveal text is replaced. That is intended: one reveal per tap, confetti already fired.

`KidHome.astro`: import `MysteryBoxCard` and `type { MysteryView } from "../../lib/mystery"`; Props `/** UX-D4b mystery box; null = boxes off for this family (or not a kid). */ mystery: MysteryView | null;`; destructure `mystery`; render `{mystery && <MysteryBoxCard view={mystery} lang={lang} starMode={starMode} />}` between the `CheckinCard` line and the `QuestCard` line.

`dashboard.astro`: import `{ mysteryView } from "../lib/mystery"`; add `{ data: mysteryResp }` after `checkinResp` in the destructuring and `// UX-D4b. apiFetch never throws; null → no card.` `apiFetch<any>("/api/progress/mystery", { token }),` as the last call; `const mystery = mysteryView(mysteryResp);`; pass `mystery={mystery}` to `<KidHome>`.

- [ ] **Step 4: Run** `npx vitest run test/mystery.test.ts test/mystery-card.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts test/contrast.test.ts` — PASS. `npm run check` — 0 errors. Whole suite — PASS.

- [ ] **Step 5: Mutation checks** — (a) `closedCount: unopened.length` → `1`: "an empty but enabled family still gets a view" fails. (b) drop the ` ×${…}` suffix: "closed: one box, or several with a count" fails. (c) star-mode branch removed: the `+12 ⭐` assertion fails. Restore each.

- [ ] **Step 6: Commit** `feat(ux-d4b): mystery box card on the kid home`

---

### Task 5: Frontend — parents (deliveries, opt-in card, settings + jar)

**Files:**
- Create: `frontend/src/components/home/DeliverStrip.astro`, `frontend/src/pages/api/families/surprises/[...path].ts`
- Modify: `frontend/src/pages/parent/index.astro`, `frontend/src/pages/parent/settings/family.astro`
- Test: `frontend/test/mystery-parent.test.ts`

**Interfaces:**
- Consumes: `GET /api/progress/mystery/deliveries`, `POST /api/progress/mystery/{id}/delivered`, `GET/POST/DELETE /api/families/surprises`, `PATCH /api/families/me {mystery_box_points}`.

- [ ] **Step 1: Write the failing test**

```ts
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const hub = read("../src/pages/parent/index.astro");
const strip = read("../src/components/home/DeliverStrip.astro");
const settings = read("../src/pages/parent/settings/family.astro");

describe("parent hub — surprises to deliver", () => {
    it("fetches the deliveries and renders the strip above the hub", () => {
        expect(hub).toMatch(/apiFetch<any\[\]>\("\/api\/progress\/mystery\/deliveries", \{ token \}\)/);
        expect(hub).toMatch(/<DeliverStrip items=\{deliveries\} lang=\{lang\} \/>/);
        expect(hub.indexOf("<DeliverStrip")).toBeLessThan(hub.indexOf("<ParentHub"));
    });
    it("the strip hides when empty, names the kid and the surprise, and marks delivered through the proxied route", () => {
        expect(strip).toMatch(/<section data-deliver-root[^>]*hidden=\{items\.length === 0\}/);
        expect(strip).toContain("Por entregar");
        expect(strip).toContain("To deliver");
        expect(strip).toContain("Entregada ✓");
        expect(strip).toContain("Delivered ✓");
        expect(strip).toMatch(/data-deliver-id=\{it\.id\}/);
        expect(strip).toMatch(/fetch\(`\/api\/progress\/mystery\/\$\{id\}\/delivered`, \{ method: "POST"/);
        expect(strip).toMatch(/showToast\(/);
        expect(strip).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(existsSync(path("../src/pages/api/progress/[...path].ts"))).toBe(true);
    });
});

describe("parent hub — mystery box opt-in card", () => {
    const banner = hub.match(/<div id="mystery-intro-banner"[\s\S]*?<\/div>\s*\)\}/)?.[0] ?? "";
    it("shows only to an undecided family and offers both answers", () => {
        expect(hub).toMatch(/\{family && family\.mystery_box_points == null && \(/);
        expect(banner).toContain("Nuevo: la caja sorpresa");
        expect(banner).toContain("New: the mystery box");
        expect(banner).toMatch(/id="mystery-intro-on"/);
        expect(banner).toMatch(/id="mystery-intro-off"/);
        expect(banner).toContain('href="/parent/settings/family#mystery-section"');
        expect(hub).toMatch(/JSON\.stringify\(\{ mystery_box_points: points \}\)/);
        expect(hub).toMatch(/mysteryIntroDecide\(20\)/);
        expect(hub).toMatch(/mysteryIntroDecide\(0\)/);
        expect(hub).toMatch(/if \(r\.ok\) document\.getElementById\("mystery-intro-banner"\)\?\.remove\(\);/);
    });
});

describe("family settings — mystery box section", () => {
    const section = settings.match(/<section[^>]*id="mystery-section"[\s\S]*?<\/section>/)?.[0] ?? "";
    it("sits after the teen check-in section and before modules", () => {
        expect(section).not.toBe("");
        expect(settings.indexOf('id="teen-checkin-section"')).toBeLessThan(settings.indexOf('id="mystery-section"'));
        expect(settings.indexOf('id="mystery-section"')).toBeLessThan(settings.indexOf('id="modules-section"'));
    });
    it("has the bounded points field, pre-filled, with zero meaning off", () => {
        const input = section.match(/<input[^>]*id="mystery-points"[^>]*>/s)?.[0] ?? "";
        expect(input).toMatch(/type="number"/);
        expect(input).toMatch(/min="0"/);
        expect(input).toMatch(/max="500"/);
        expect(input).toMatch(/value=\{family\?\.mystery_box_points \?\? ""\}/);
        expect(settings).toMatch(/mystery_box_points: value/);
        expect(settings).toMatch(/const raw = pointsInput\.value\.trim\(\);/);
    });
    it("renders the jar from the server and adds / removes through the proxied route", () => {
        expect(settings).toMatch(/apiFetch<any\[\]>\("\/api\/families\/surprises", \{ token \}\)/);
        expect(section).toMatch(/data-jar-list/);
        expect(section).toMatch(/data-jar-remove=\{s\.id\}/);
        expect(section).toMatch(/id="jar-title"[^>]*maxlength="60"/);
        expect(section).toMatch(/id="jar-emoji"[^>]*maxlength="4"/);
        expect(settings).toMatch(/fetch\("\/api\/families\/surprises", \{\s*method: "POST"/);
        expect(settings).toMatch(/fetch\(`\/api\/families\/surprises\/\$\{id\}`, \{ method: "DELETE"/);
        expect(settings).toMatch(/showToast\(/);
        expect(existsSync(path("../src/pages/api/families/surprises/[...path].ts"))).toBe(true);
    });
    it("explains the box in both languages", () => {
        expect(section).toContain("Cuando un hijo termina todas sus tareas del día, le aparece una caja sorpresa.");
        expect(section).toContain("When a kid finishes every chore of the day, a mystery box appears.");
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/mystery-parent.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement**

`frontend/src/pages/api/families/surprises/[...path].ts`:

```ts
import { createApiProxy } from "../../../../lib/server/proxy";

// UX-D4b: the surprise jar (GET/POST /api/families/surprises, DELETE
// /api/families/surprises/{id}). A rest route matches the bare path too.
export const { GET, POST, DELETE } = createApiProxy({ name: "families-surprises" });
```

(Check `createApiProxy`'s options type: if `name` must be one of a fixed list, follow whatever the other route files pass.)

`frontend/src/components/home/DeliverStrip.astro`:

```astro
---
/**
 * UX-D4b: surprises the kids revealed that a parent has not handed over yet.
 * One row per surprise; "Delivered ✓" removes the row after a 2xx; the whole
 * strip hides when nothing is left.
 */
import { buttonClass } from "../../lib/buttonClasses";

interface Props {
    items: { id: string; kid_name: string; surprise_title: string; surprise_emoji?: string | null; day: string }[];
    lang: "es" | "en";
}
const { items, lang } = Astro.props;
const es = lang === "es";
---

<section data-deliver-root data-lang={lang} hidden={items.length === 0} class="max-w-md mx-auto w-full mb-6" aria-labelledby="deliver-heading">
    <h2 id="deliver-heading" class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft mb-2 px-1">
        {es ? "Por entregar" : "To deliver"}
    </h2>
    <ul class="space-y-2">
        {items.map((it) => (
            <li data-deliver-id={it.id} class="flex items-center gap-3 rounded-2xl border border-brand-ink/10 bg-white p-3 shadow-[var(--shadow-card)]">
                <span class="text-2xl" aria-hidden="true">{it.surprise_emoji || "🎁"}</span>
                <span class="min-w-0 flex-1 text-sm text-brand-ink">
                    <span class="font-bold">{it.kid_name}</span> — <span class="italic">{it.surprise_title}</span>
                </span>
                <button type="button" data-deliver-done class={buttonClass("secondary", "sm")}>{es ? "Entregada ✓" : "Delivered ✓"}</button>
            </li>
        ))}
    </ul>
</section>

<script>
    import { showToast } from "../../lib/toast";

    const root = document.querySelector<HTMLElement>("[data-deliver-root]");
    if (root) {
        const es = root.dataset.lang !== "en";
        root.querySelectorAll<HTMLButtonElement>("[data-deliver-done]").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const row = btn.closest<HTMLElement>("[data-deliver-id]");
                const id = row?.dataset.deliverId;
                if (!row || !id) return;
                btn.disabled = true;
                try {
                    const r = await fetch(`/api/progress/mystery/${id}/delivered`, { method: "POST", credentials: "same-origin" });
                    if (!r.ok) throw new Error(String(r.status));
                    row.remove();
                    if (!root.querySelector("[data-deliver-id]")) root.setAttribute("hidden", "");
                } catch {
                    btn.disabled = false;
                    showToast(es ? "No se pudo guardar. Intenta de nuevo." : "Could not save. Try again.", "error");
                }
            });
        });
    }
</script>
```

`parent/index.astro`: import `DeliverStrip from "@components/home/DeliverStrip.astro"` (match the import style the file uses for `ParentHub`); add `apiFetch<any[]>("/api/progress/mystery/deliveries", { token })` to the frontmatter's parallel fetches as `deliveriesRes`, `const deliveries = deliveriesRes.data ?? [];`; render `<DeliverStrip items={deliveries} lang={lang} />` right before `<ParentHub`; add the opt-in banner after the teen check-in banner:

```astro
    {family && family.mystery_box_points == null && (
        <div id="mystery-intro-banner" class="max-w-md mx-auto w-full mb-6 bg-brand-sky/10 border border-brand-sky/30 rounded-2xl p-5 shadow-[var(--shadow-card)]">
            <h2 class="font-bold text-brand-ink text-base mb-1">
                {lang === "es" ? "Nuevo: la caja sorpresa" : "New: the mystery box"}
            </h2>
            <p class="text-sm text-brand-ink-soft mb-3">
                {lang === "es"
                    ? "Cuando un hijo termina todas sus tareas del día, le aparece una caja sorpresa. Dentro va una sorpresa de tu frasco (tú las escribes) o, si el frasco está vacío, hasta 20 puntos. "
                    : "When a kid finishes every chore of the day, a mystery box appears. Inside is a surprise from your jar (you write them) or, if the jar is empty, up to 20 points. "}
                <a href="/parent/settings/family#mystery-section" class="text-brand-sky-text font-semibold hover:underline">
                    {lang === "es" ? "Llenar el frasco" : "Fill the jar"}
                </a>
            </p>
            <div class="flex flex-wrap gap-2">
                <button id="mystery-intro-on" class={buttonClass("secondary", "sm")}>
                    {lang === "es" ? "Activar" : "Turn on"}
                </button>
                <button id="mystery-intro-off"
                        class="px-4 py-2 rounded-lg bg-brand-cream-deep text-brand-ink text-xs font-semibold hover:bg-brand-cream border border-brand-ink/15 transition-colors">
                    {lang === "es" ? "Ahora no" : "Not now"}
                </button>
            </div>
        </div>
    )}
```

and in the opt-in script, after `checkinIntroDecide`:

```ts
    // UX-D4b mystery box opt-in: 20 turns boxes on with the default maximum, 0 is "not now".
    const mysteryIntroDecide = async (points: number) => {
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mystery_box_points: points }),
            });
            if (r.ok) document.getElementById("mystery-intro-banner")?.remove();
        } catch (e) {
            console.error("mystery box opt-in decision failed:", e);
        }
    };
    document.getElementById("mystery-intro-on")?.addEventListener("click", () => mysteryIntroDecide(20));
    document.getElementById("mystery-intro-off")?.addEventListener("click", () => mysteryIntroDecide(0));
```

`parent/settings/family.astro` — frontmatter: `const { data: jar } = await apiFetch<any[]>("/api/families/surprises", { token });` `const surprises: any[] = jar ?? [];` (next to the family fetch). Section, after `#teen-checkin-section`:

```astro
    <section class="mt-4 bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10 space-y-4" id="mystery-section"
             data-lang={lang}
             data-saved={lang === "es" ? "Guardado." : "Saved."}
             data-error={lang === "es" ? "No se pudo guardar. Intenta de nuevo." : "Could not save. Try again."}
             data-range={lang === "es" ? "Usa un número entero de 0 a 500." : "Use a whole number from 0 to 500."}
             data-full={lang === "es" ? "El frasco está lleno (20)." : "The jar is full (20)."}>
        <h2 class="text-sm font-bold text-brand-ink">🎁 {lang === "es" ? "Caja sorpresa" : "Mystery box"}</h2>
        <p class="text-xs text-brand-ink-soft">
            {lang === "es"
                ? "Cuando un hijo termina todas sus tareas del día, le aparece una caja sorpresa. Dentro va una sorpresa del frasco o, si está vacío, puntos."
                : "When a kid finishes every chore of the day, a mystery box appears. Inside is a surprise from the jar or, if it is empty, points."}
        </p>
        <div>
            <label for="mystery-points" class="block text-sm font-semibold text-brand-ink mb-1">
                {lang === "es" ? "Puntos máximos cuando el frasco está vacío" : "Maximum points when the jar is empty"}
            </label>
            <div class="flex items-center gap-3">
                <input type="number" id="mystery-points" inputmode="numeric" min="0" max="500" step="1"
                       value={family?.mystery_box_points ?? ""} placeholder="20"
                       class="w-32 rounded-lg border border-brand-ink/20 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-sky" />
                <button type="button" id="mystery-save" class={`disabled:opacity-60 ${buttonClass("secondary", "sm")}`}>
                    {lang === "es" ? "Guardar" : "Save"}
                </button>
                <span id="mystery-status" class="text-sm" aria-live="polite"></span>
            </div>
            <p class="text-xs text-brand-ink-soft mt-1">
                {lang === "es" ? "Entre la cuarta parte y este máximo. 0 apaga las cajas." : "Between a quarter and this maximum. 0 turns boxes off."}
            </p>
        </div>
        <div>
            <h3 class="text-sm font-semibold text-brand-ink">{lang === "es" ? "Frasco de sorpresas" : "Surprise jar"}</h3>
            <p class="text-xs text-brand-ink-soft mt-1 mb-2">
                {lang === "es"
                    ? "Cosas pequeñas y reales: \"elige el postre\", \"30 min más de pantalla\". Se reutilizan; nunca la misma dos días seguidos."
                    : "Small, real things: \"pick dessert\", \"30 more minutes of screen time\". Reused; never the same one two days in a row."}
            </p>
            <ul data-jar-list class="space-y-1">
                {surprises.map((s: any) => (
                    <li data-jar-item={s.id} class="flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm text-brand-ink border border-brand-ink/10">
                        <span aria-hidden="true">{s.emoji || "🎁"}</span>
                        <span class="min-w-0 flex-1">{s.title}</span>
                        <button type="button" data-jar-remove={s.id} class="text-xs font-semibold text-red-700 hover:underline">
                            {lang === "es" ? "Quitar" : "Remove"}
                        </button>
                    </li>
                ))}
            </ul>
            <div class="mt-2 flex flex-wrap items-center gap-2">
                <input type="text" id="jar-emoji" maxlength="4" placeholder="🎉" aria-label="Emoji"
                       class="w-14 rounded-lg border border-brand-ink/20 bg-white px-2 py-2 text-center text-sm focus:outline-none focus:ring-2 focus:ring-brand-sky" />
                <input type="text" id="jar-title" maxlength="60" placeholder={lang === "es" ? "Elige el postre de hoy" : "Pick tonight's dessert"}
                       aria-label={lang === "es" ? "Sorpresa" : "Surprise"}
                       class="min-w-0 flex-1 rounded-lg border border-brand-ink/20 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-sky" />
                <button type="button" id="jar-add" class={buttonClass("secondary", "sm")}>{lang === "es" ? "Agregar" : "Add"}</button>
            </div>
        </div>
    </section>
```

Script (after the teen check-in script):

```astro
<script>
    import { showToast } from "../../../lib/toast";

    const section = document.getElementById("mystery-section");
    const pointsInput = document.getElementById("mystery-points") as HTMLInputElement | null;
    const save = document.getElementById("mystery-save") as HTMLButtonElement | null;
    const status = document.getElementById("mystery-status");
    save?.addEventListener("click", async () => {
        if (!section || !pointsInput || !status) return;
        const raw = pointsInput.value.trim();
        const value = Number(raw);
        status.className = "text-sm";
        if (raw === "" || !Number.isInteger(value) || value < 0 || value > 500) {
            status.textContent = section.dataset.range ?? "";
            status.className = "text-sm text-red-700";
            return;
        }
        save.setAttribute("disabled", "true");
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mystery_box_points: value }),
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

    // The jar: add appends a row, remove deletes one; both through the API.
    const list = section?.querySelector<HTMLElement>("[data-jar-list]");
    const title = document.getElementById("jar-title") as HTMLInputElement | null;
    const emoji = document.getElementById("jar-emoji") as HTMLInputElement | null;
    const add = document.getElementById("jar-add") as HTMLButtonElement | null;
    const es = section?.dataset.lang === "es";

    const wireRemove = (btn: HTMLButtonElement) => {
        btn.addEventListener("click", async () => {
            const id = btn.dataset.jarRemove;
            if (!id) return;
            btn.disabled = true;
            try {
                const r = await fetch(`/api/families/surprises/${id}`, { method: "DELETE", credentials: "same-origin" });
                if (!r.ok) throw new Error(String(r.status));
                btn.closest("[data-jar-item]")?.remove();
            } catch {
                btn.disabled = false;
                showToast(section?.dataset.error ?? "", "error");
            }
        });
    };
    list?.querySelectorAll<HTMLButtonElement>("[data-jar-remove]").forEach(wireRemove);

    add?.addEventListener("click", async () => {
        if (!list || !title || !section) return;
        const text = title.value.trim();
        if (!text) { title.focus(); return; }
        if (list.querySelectorAll("[data-jar-item]").length >= 20) { showToast(section.dataset.full ?? "", "info"); return; }
        add.disabled = true;
        try {
            const r = await fetch("/api/families/surprises", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: text, emoji: emoji?.value.trim() || null }),
            });
            if (!r.ok) throw new Error(String(r.status));
            const s = await r.json();
            const li = document.createElement("li");
            li.dataset.jarItem = s.id;
            li.className = "flex items-center gap-2 rounded-lg bg-white px-3 py-2 text-sm text-brand-ink border border-brand-ink/10";
            const icon = document.createElement("span"); icon.setAttribute("aria-hidden", "true"); icon.textContent = s.emoji || "🎁";
            const label = document.createElement("span"); label.className = "min-w-0 flex-1"; label.textContent = s.title;
            const btn = document.createElement("button"); btn.type = "button"; btn.dataset.jarRemove = s.id;
            btn.className = "text-xs font-semibold text-red-700 hover:underline"; btn.textContent = es ? "Quitar" : "Remove";
            wireRemove(btn);
            li.append(icon, label, btn);
            list.appendChild(li);
            title.value = ""; if (emoji) emoji.value = "";
            showToast(section.dataset.saved ?? "", "success");
        } catch {
            showToast(section.dataset.error ?? "", "error");
        } finally {
            add.disabled = false;
        }
    });
</script>
```

- [ ] **Step 4: Run** `npx vitest run test/mystery-parent.test.ts test/checkin-parent.test.ts test/quest-settings.test.ts test/quest-intro.test.ts test/parent-hub.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts test/contrast.test.ts` — PASS. `npm run check` — 0 errors. `npm run build` — succeeds.

- [ ] **Step 5: Commit** `feat(ux-d4b): surprises to deliver, opt-in card, settings and jar`

---

### Task 6: Docs

**Files:**
- Modify: `docs/USER_GUIDE_EN.md`, `docs/USER_GUIDE_ES.md`, `CLAUDE.md`

- [ ] **Step 1:** EN guide — TOC entry after 17.5.5: `        - [17.5.6 Mystery Box](#1756-mystery-box)`; section after 17.5.5's last paragraph (before the `---` that precedes Chapter 18):

```markdown
## 17.5.6 Mystery Box

Finish every chore of the day and a closed box appears on your home screen: "🎁 A mystery box! Tap to open". Inside is one of two things:

- a **surprise** your parents wrote into the family's jar — "Pick dessert tonight", "30 more minutes of screen time" — picked at random, never the same one two days in a row;
- **points** when the jar is empty: between a quarter of the family's maximum and the maximum (20 by default).

One box per day. A box never expires: if you did not open it, it waits for you. A surprise you reveal shows up on your parents' home screen under **To deliver** until they hand it over.

> **For parents:** turn boxes on in **Settings → Family → Mystery box**, set the points maximum (0 turns boxes off), and fill the **surprise jar** — up to 20 short surprises, reused forever, removable any time. Families that were already using the app start with boxes off: a card on your home screen asks once.
```

- [ ] **Step 2:** ES guide — TOC `        - [17.5.6 Caja Sorpresa](#1756-caja-sorpresa)`; section (unaccented, the file's style):

```markdown
## 17.5.6 Caja Sorpresa

Termina todas tus tareas del dia y aparece una caja cerrada en tu pantalla de inicio: "🎁 ¡Una caja sorpresa! Toca para abrir". Adentro hay una de dos cosas:

- una **sorpresa** que tus papas escribieron en el frasco de la familia — "elige el postre", "30 minutos mas de pantalla" — al azar, nunca la misma dos dias seguidos;
- **puntos** cuando el frasco esta vacio: entre la cuarta parte del maximo de la familia y ese maximo (20 por defecto).

Una caja por dia. Una caja no caduca: si no la abriste, te espera. Una sorpresa que revelas aparece en la pantalla de tus papas bajo **Por entregar** hasta que te la den.

> **Para papas:** activa las cajas en **Ajustes → Familia → Caja sorpresa**, define el maximo de puntos (0 apaga las cajas) y llena el **frasco de sorpresas**: hasta 20 sorpresas cortas, que se reutilizan y puedes quitar cuando quieras. Las familias que ya usaban la app empiezan con las cajas apagadas: una tarjeta en tu pantalla de inicio pregunta una sola vez.
```

- [ ] **Step 3:** `CLAUDE.md` — Progress row label → `(UX-D1, UX-D2, UX-D3, UX-D4a, UX-D4b)` and append to its notes:

```
**Mystery box** (D4b): `mystery_service.py`. A PERFECT day (the streak's `DayState.done` for today, counted at submit) creates one closed `mystery_boxes` row per kid per day on read (`GET /api/progress/mystery`); the content is decided and paid once at opening (`POST …/{id}/open`, guarded UPDATE on `opened_at`): a random surprise from the family's jar (`mystery_surprises`, ≤ 20, reusable, never the kid's last one) with the title copied onto the box, else `randint(max(1, M//4), M)` points as a `bonus` transaction. `families.mystery_box_points` is three-state like the quest bonus (NULL undecided → hub card, 0 off, > 0 on; new families 20; existing reset to NULL by the migration). A family at 0/NULL cannot open a box (409) — it waits. Surprises land on the parent hub as "To deliver" (`…/deliveries`, `…/{id}/delivered`). Copy only in `frontend/src/lib/mystery.ts`; the card is hidden until a box exists and wakes on `ftm:deck-empty`. No job, no notification, no LLM.
```

- [ ] **Step 4:** `npx vitest run` and `npm run build` — PASS. `grep -n "1756" docs/USER_GUIDE_*.md` shows the entry and heading in each file.

- [ ] **Step 5: Commit** `docs(ux-d4b): guides and CLAUDE.md for the mystery box`

---

## After the tasks

1. Schema parity on a fresh scratch DB (`familyapp_d4b_mig` / `_orm` — the local server cannot drop databases, so new names each time).
2. Final whole-branch review (one fresh reviewer, most capable model) with the Review Focus list; one fix pass, each fix RED→GREEN.
3. Push → PR → watch CI → merge explicitly → sync main → `./scripts/deploy-onprem.sh -y`.
4. Prod check in the demo family only (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`, verified by id): mariana — hub card → Turn on; settings → add two surprises; sofia or diego — finish today's chores (or pick the kid whose day is already perfect) → box appears → open → reveal; mariana — "To deliver" row → Delivered ✓; the kid's second open returns the same content. Leave the demo family on.
