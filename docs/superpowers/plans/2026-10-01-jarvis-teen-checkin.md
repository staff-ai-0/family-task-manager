# Jarvis Teen Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a teen has a late or sent-back chore, Jarvis offers help on their home; the one-tap reason they pick is stored so the product owner can count, across families, why chores do not get done.

**Architecture:** One family-scoped table (`teen_checkins`) and one three-state family switch. A small service (`teen_checkin_service.py`) holds the pure rules (who is offered what, how often) and two family-scoped operations (`offer_for`, `record`); the server always re-derives the offer, so the client can only answer the chore it was actually offered. The operator summary is the only cross-family read and lives in `app/services/admin/`. No LLM call anywhere in this feature.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest · Astro 5 + vitest (node; source-structure tests for `.astro`).

**Spec:** `docs/superpowers/specs/2026-10-01-jarvis-teen-checkin-design.md`

## Global Constraints

- Family isolation: every query filters by `family_id`, except `AdminReadService.teen_checkin_summary` (behind `require_superadmin`).
- Teens only (role `TEEN`). Parents and children never get an offer and can never store a row.
- Reasons, exactly: `too_hard`, `not_clear`, `no_time`, `not_fair`, `forgot`, `app_problem`, `other`. A note is allowed only for `app_problem` and `other`, at most 200 characters.
- Limits: 1 offer per family-local day, 3 per Monday–Sunday week, a `dismissed` row blocks offers for 7 days (the day it was made plus six), candidate chores are dated within the last 14 days (today included), a chore is asked about once.
- The chore title is never stored in `teen_checkins`. The operator response never contains a family id, a user id, an assignment id, or a name.
- `families.teen_checkin_enabled`: `NULL` = undecided (off), `false` = off, `true` = on. No default — every family starts `NULL`.
- Migration revision `teen_checkins`, down-revision `family_smart_reminders`.
- Every path browser code calls must have an Astro `/api` route file (`/api/jarvis/[...path].ts`, `/api/families/me.ts`, `/api/admin/[...path].ts` already exist) — keep the guard tests.
- Frontend: no native `alert`/`confirm`/`prompt`; kit classes; `hidden` attribute (not class) for toggled elements; emoji never in an `<h1>`.
- Tests never hard-code a calendar date.
- Never run the whole backend suite locally in one call; run the named files. CI runs the suite.
- Local backend tests: `$SP/pt.sh <files>` style — `export TZ=UTC REDIS_URL=redis://localhost:6379/0 UPLOADS_ROOT=<scratchpad>/uploads TEST_DATABASE_URL=postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test DATABASE_URL=<same>; cd backend && timeout 900 /Users/jc/dev-2026/AgentIA/family-task-manager/backend/.venv/bin/pytest -q --no-cov -p no:warnings <files> </dev/null`. Lint `/opt/homebrew/bin/ruff check app`. Frontend: `npm ci` once, `timeout 300 npx vitest run <files> </dev/null`, `npm run check`, `npm run build`.
- Commit trailer: `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **A client that lies** — POSTing an `assignment_id` that is another teen's, another family's, not late, already asked, or simply not the current offer must store nothing (Tasks 2, 3).
2. **Identity leak to the operator** — no id or name in the summary, including inside nested objects (Task 4).
3. **Nagging** — after any answer or dismissal the same day shows no card; "Not now" really pauses a week (Tasks 2, 5).
4. **A note with the wrong reason** — rejected (422), not silently stored or silently dropped (Task 3); and the DB refuses it even if the API is bypassed (Task 1).
5. **Undecided is off** — a family that never answered the hub card gets no offers and stores nothing (Task 2).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/models/teen_checkin.py` (new) | the table |
| `backend/migrations/versions/2026_10_01_teen_checkins.py` (new) | table + `families.teen_checkin_enabled` |
| `backend/app/models/{__init__,family}.py`, `backend/app/schemas/family.py` | registration, column, schema fields |
| `backend/app/services/family_export_service.py` | export registry + `jarvis/teen_checkins.json` |
| `backend/app/services/teen_checkin_service.py` (new) | rules, `offer_for`, `record` |
| `backend/app/api/routes/jarvis.py` | `GET`/`POST /api/jarvis/checkin` |
| `backend/app/services/admin/admin_read_service.py`, `backend/app/api/routes/admin/overview.py` | operator summary |
| `frontend/src/lib/checkin.ts` (new) | copy, tips, request bodies, chat link |
| `frontend/src/components/home/CheckinCard.astro` (new), `KidHome.astro`, `pages/dashboard.astro` | the teen card |
| `frontend/src/pages/parent/index.astro`, `parent/settings/family.astro` | opt-in card, settings checkbox |
| `frontend/src/pages/admin/feedback.astro` (new), `components/ui/AdminShell.astro` | operator page |
| `frontend/src/pages/privacidad.astro`, `docs/USER_GUIDE_{EN,ES}.md`, `CLAUDE.md` | docs |

---

### Task 1: Data model, family switch, export

**Files:**
- Create: `backend/app/models/teen_checkin.py`, `backend/migrations/versions/2026_10_01_teen_checkins.py`
- Modify: `backend/app/models/__init__.py`, `backend/app/models/family.py`, `backend/app/schemas/family.py`, `backend/app/services/family_export_service.py`
- Test: `backend/tests/test_teen_checkin_model.py`

**Interfaces:**
- Produces: `TeenCheckin` (columns `id, family_id, user_id, assignment_id, trigger, outcome, reason, note, days_late, points, lang, created_at`); constraint `uq_teen_checkins_family_user_assignment`; `Family.teen_checkin_enabled: Optional[bool]`; `PATCH /api/families/me {"teen_checkin_enabled": bool|null}`; `FamilyResponse.teen_checkin_enabled: Optional[bool]`; export file `jarvis/teen_checkins.json`.

- [ ] **Step 1: Write the failing tests**

```python
"""Jarvis teen check-in: the table, its guards, the family switch, the export."""
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.services.family_export_service import EXPORTED_FAMILY_TABLES
from app.services.progress_service import ProgressService

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_10_01_teen_checkins.py"
)


class _RecordingOp:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("teen_checkins", MIGRATION)
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
    assert mod.revision == "teen_checkins"
    assert mod.down_revision == "family_smart_reminders"


def test_upgrade_adds_an_undecided_switch_and_the_table():
    calls = _run("upgrade")
    adds = [a for n, a, _k in calls if n == "add_column"]
    assert len(adds) == 1 and adds[0][0] == "families"
    column = adds[0][1]
    assert column.name == "teen_checkin_enabled" and column.nullable is True
    assert column.server_default is None                       # every family starts undecided
    tables = [a for n, a, _k in calls if n == "create_table"]
    assert [t[0] for t in tables] == ["teen_checkins"]
    names = {getattr(c, "name", None) for c in tables[0][1:]}
    assert {"uq_teen_checkins_family_user_assignment", "ck_teen_checkins_reason_iff_answered",
            "ck_teen_checkins_note_reason", "ck_teen_checkins_note_len"} <= names
    assert "title" not in names and "template_title" not in names


def test_reverse_migration_removes_both():
    calls = _run("downgrade")
    assert ("drop_table", ("teen_checkins",), {}) in calls
    assert ("drop_column", ("families", "teen_checkin_enabled"), {}) in calls


async def _assignment(db, teen):
    today, _tz = await ProgressService.family_today(db, teen.family_id)
    template = TaskTemplate(id=uuid4(), title="Clean Diego's room", points=15, interval_days=1,
                            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=teen.family_id)
    db.add(template)
    await db.commit()
    day = today - timedelta(days=1)
    a = TaskAssignment(family_id=teen.family_id, template_id=template.id, assigned_to=teen.id,
                       status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


def _row(teen, assignment, **kw):
    base = dict(family_id=teen.family_id, user_id=teen.id, assignment_id=assignment.id, trigger="late",
                outcome="answered", reason="too_hard", note=None, days_late=1, points=15, lang="en",
                created_at=datetime.now(timezone.utc))
    base.update(kw)
    return TeenCheckin(**base)


class TestTable:
    async def test_a_valid_answer_is_stored(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.trigger, row.outcome, row.reason, row.note) == ("late", "answered", "too_hard", None)
        assert not hasattr(row, "title")

    @pytest.mark.parametrize("bad", [
        dict(outcome="answered", reason=None),                       # an answer needs a reason
        dict(outcome="dismissed", reason="forgot"),                  # a dismissal has none
        dict(reason="too_hard", note="my brother never does his"),   # notes only for app_problem / other
        dict(reason="other", note="x" * 201),                        # 200 characters at most
        dict(reason="because"),                                      # not one of the seven
        dict(trigger="bored"),
        dict(outcome="maybe"),
        dict(days_late=-1),
    ])
    async def test_the_database_refuses_bad_rows(self, db_session, test_teen_user, bad):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a, **bad))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_notes_are_allowed_for_the_two_open_reasons(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a, reason="app_problem", note="x" * 200))
        await db_session.commit()

    async def test_a_chore_is_asked_about_once(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        db_session.add(_row(test_teen_user, a, outcome="dismissed", reason=None))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_the_row_survives_its_chore(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        await db_session.execute(delete(TaskAssignment).where(TaskAssignment.id == a.id))
        await db_session.commit()
        db_session.expire_all()
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert row.assignment_id is None and row.reason == "too_hard"


class TestFamilySwitch:
    async def test_every_family_starts_undecided(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["teen_checkin_enabled"] is None

    async def test_a_parent_can_turn_it_on_and_off(self, client, auth_headers, db_session, test_family):
        for value in (True, False):
            r = await client.patch("/api/families/me", json={"teen_checkin_enabled": value}, headers=auth_headers)
            assert r.status_code == 200 and r.json()["teen_checkin_enabled"] is value
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is False

    async def test_other_updates_leave_it_alone(self, client, auth_headers, db_session, test_family):
        await client.patch("/api/families/me", json={"teen_checkin_enabled": True}, headers=auth_headers)
        await client.patch("/api/families/me", json={"quest_bonus_points": 30}, headers=auth_headers)
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is True

    async def test_a_teen_cannot_change_it(self, client, db_session, test_family, test_teen_user):
        login = await client.post("/api/auth/login", json={"email": "teen@test.com", "password": "password123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.patch("/api/families/me", json={"teen_checkin_enabled": True}, headers=headers)
        assert r.status_code in (401, 403)
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is None


def test_the_table_is_part_of_the_family_export():
    assert "teen_checkins" in EXPORTED_FAMILY_TABLES
```

- [ ] **Step 2: Run** `pytest tests/test_teen_checkin_model.py` — Expected: FAIL at import (`No module named app.models.teen_checkin`).

- [ ] **Step 3: Implement**

`backend/app/models/teen_checkin.py`:

```python
"""Jarvis teen check-in: one row per offer a teen acted on.

When a teen has a late or sent-back chore, Jarvis offers a hand on their home.
The teen either answers with a one-tap reason or says "not now"; that is this
row. It is what the product owner counts across families (operator console),
so it deliberately carries NO chore title — titles are written by the family
and can contain names. A short note is kept only for the two open reasons.
"""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class TeenCheckin(Base):
    __tablename__ = "teen_checkins"
    __table_args__ = (
        # A chore is asked about once, ever.
        UniqueConstraint("family_id", "user_id", "assignment_id", name="uq_teen_checkins_family_user_assignment"),
        CheckConstraint("trigger IN ('late','sent_back')", name="ck_teen_checkins_trigger"),
        CheckConstraint("outcome IN ('answered','dismissed')", name="ck_teen_checkins_outcome"),
        CheckConstraint(
            "reason IS NULL OR reason IN "
            "('too_hard','not_clear','no_time','not_fair','forgot','app_problem','other')",
            name="ck_teen_checkins_reason",
        ),
        CheckConstraint("(outcome = 'answered') = (reason IS NOT NULL)", name="ck_teen_checkins_reason_iff_answered"),
        CheckConstraint("note IS NULL OR reason IN ('app_problem','other')", name="ck_teen_checkins_note_reason"),
        CheckConstraint("note IS NULL OR char_length(note) <= 200", name="ck_teen_checkins_note_len"),
        CheckConstraint("days_late >= 0", name="ck_teen_checkins_days_late"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL: deleting the chore keeps the answer (the counts stay true).
    assignment_id = Column(
        UUID(as_uuid=True), ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True
    )
    trigger = Column(String(16), nullable=False)       # late | sent_back
    outcome = Column(String(16), nullable=False)       # answered | dismissed
    reason = Column(String(16), nullable=True)         # one of the seven keys; NULL when dismissed
    # TEXT, bounded by ck_teen_checkins_note_len: an over-long note is refused by
    # the constraint (one error type for every bad row), not by a column width.
    note = Column(Text, nullable=True)                 # only for app_problem / other
    days_late = Column(Integer, nullable=False)        # chore date → the day of the answer
    points = Column(Integer, nullable=False)           # the chore's points: a size signal, not an identity
    lang = Column(String(2), nullable=False)           # es | en — for reading notes
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    def __repr__(self):
        return f"<TeenCheckin(user_id={self.user_id}, outcome={self.outcome}, reason={self.reason})>"
```

Migration:

```python
"""teen_checkins + families.teen_checkin_enabled (Jarvis teen check-in)

Revision ID: teen_checkins
Revises: family_smart_reminders
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "teen_checkins"
down_revision = "family_smart_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No default: NULL = undecided. Check-ins store a minor's answers for the
    # product team, so every family — existing and new — must say yes first.
    op.add_column("families", sa.Column("teen_checkin_enabled", sa.Boolean(), nullable=True))
    op.create_table(
        "teen_checkins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("days_late", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "user_id", "assignment_id", name="uq_teen_checkins_family_user_assignment"),
        sa.CheckConstraint("trigger IN ('late','sent_back')", name="ck_teen_checkins_trigger"),
        sa.CheckConstraint("outcome IN ('answered','dismissed')", name="ck_teen_checkins_outcome"),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('too_hard','not_clear','no_time','not_fair','forgot','app_problem','other')",
            name="ck_teen_checkins_reason",
        ),
        sa.CheckConstraint("(outcome = 'answered') = (reason IS NOT NULL)", name="ck_teen_checkins_reason_iff_answered"),
        sa.CheckConstraint("note IS NULL OR reason IN ('app_problem','other')", name="ck_teen_checkins_note_reason"),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 200", name="ck_teen_checkins_note_len"),
        sa.CheckConstraint("days_late >= 0", name="ck_teen_checkins_days_late"),
    )
    op.create_index("ix_teen_checkins_family_id", "teen_checkins", ["family_id"])
    op.create_index("ix_teen_checkins_user_id", "teen_checkins", ["user_id"])
    op.create_index("ix_teen_checkins_created_at", "teen_checkins", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_teen_checkins_created_at", table_name="teen_checkins")
    op.drop_index("ix_teen_checkins_user_id", table_name="teen_checkins")
    op.drop_index("ix_teen_checkins_family_id", table_name="teen_checkins")
    op.drop_table("teen_checkins")
    op.drop_column("families", "teen_checkin_enabled")
```

`models/__init__.py`: import `TeenCheckin` next to `WeeklyQuest` and add `"TeenCheckin"` to `__all__`.

`models/family.py`, after `smart_reminders_enabled`:

```python
    # Jarvis teen check-in. NULL = undecided (off; the parent hub shows a
    # one-time card in families that have a teen), False = off by choice,
    # True = on. No default on purpose: it stores a minor's answers for the
    # product team, so every family must say yes first.
    teen_checkin_enabled = Column(Boolean, nullable=True)
```

`schemas/family.py` — `FamilyUpdate`, after `smart_reminders_enabled`:

```python
    # Jarvis teen check-in: true = on, false = off, null = back to undecided.
    teen_checkin_enabled: Optional[bool] = None
```

`FamilyResponse`, after `smart_reminders_enabled`:

```python
    # Jarvis teen check-in: NULL = undecided (off + one-time parent-hub card).
    teen_checkin_enabled: Optional[bool] = None
```

`family_export_service.py`: import `TeenCheckin`; add it to `EXPORTED_FAMILY_TABLES` next to `WeeklyQuest`; next to the `quests` query add `teen_checkins = await _rows(db, fam(TeenCheckin))`; next to `"jarvis/pending_actions.json"` add `"jarvis/teen_checkins.json": _dump(teen_checkins),`. If the `_README` text lists the jarvis files, add the new one there too.

- [ ] **Step 4: Run** `pytest tests/test_teen_checkin_model.py tests/test_family_delete_export.py tests/test_smart_reminders_setting.py` — Expected: PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) drop `ck_teen_checkins_note_reason` from the model: the `note="my brother…"` case fails. (b) give `teen_checkin_enabled` a `server_default="true"` in the migration: `test_upgrade_adds_an_undecided_switch_and_the_table` fails. Restore each.

- [ ] **Step 6: Commit** `feat(jarvis): teen check-in table, family switch, export`

---

### Task 2: Rules and service

**Files:**
- Create: `backend/app/services/teen_checkin_service.py`
- Test: `backend/tests/test_teen_checkin_rules.py`, `backend/tests/test_teen_checkin_service.py`

**Interfaces:**
- Consumes: Task 1 model + `Family.teen_checkin_enabled`; `ProgressService.family_today`; `family_tier_allows`.
- Produces (module `app.services.teen_checkin_service`):
  - `REASONS: tuple[str, ...]`, `NOTE_REASONS: frozenset[str]`, `NOTE_MAX = 200`, `CANDIDATE_DAYS = 14`, `MAX_PER_WEEK = 3`, `PAUSE_DAYS = 7`
  - `@dataclass(frozen=True) Candidate(assignment_id: UUID, assigned_date: date, trigger: str, title: str, title_es: Optional[str], points: int)`
  - `trigger_for(status, approval, assigned_date: date, today: date) -> Optional[str]`
  - `pick_candidate(cands: list[Candidate]) -> Optional[Candidate]`
  - `may_offer(today: date, past: list[tuple[date, str]]) -> bool`
  - `normalize_note(reason: Optional[str], note: Optional[str]) -> Optional[str]` (raises `ValueError`)
  - `TeenCheckinService.offer_for(db, user) -> Optional[Candidate]`
  - `TeenCheckinService.record(db, user, assignment_id: UUID, outcome: str, reason: Optional[str], note: Optional[str]) -> bool` (`False` = not the current offer; nothing stored)
  - `TeenCheckinService.can_chat(db, family_id) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_teen_checkin_rules.py`:

```python
"""Jarvis teen check-in — pure rules."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.task_assignment import ApprovalStatus as AP, AssignmentStatus as ST
from app.services.teen_checkin_service import (
    CANDIDATE_DAYS, MAX_PER_WEEK, NOTE_MAX, NOTE_REASONS, PAUSE_DAYS, REASONS, Candidate,
    may_offer, normalize_note, pick_candidate, trigger_for,
)

TODAY = datetime.now(timezone.utc).date()
# A Wednesday near today: never a week edge, never a hard-coded date.
WED = TODAY + timedelta(days=(2 - TODAY.weekday()) % 7)


def cand(trigger, days_ago, title="x"):
    return Candidate(uuid4(), TODAY - timedelta(days=days_ago), trigger, title, None, 10)


def test_constants():
    assert REASONS == ("too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other")
    assert NOTE_REASONS == {"app_problem", "other"}
    assert (NOTE_MAX, CANDIDATE_DAYS, MAX_PER_WEEK, PAUSE_DAYS) == (200, 14, 3, 7)


class TestTrigger:
    def test_sent_back_is_a_reopened_rejected_chore_any_day(self):
        assert trigger_for(ST.PENDING, AP.REJECTED, TODAY, TODAY) == "sent_back"
        assert trigger_for(ST.PENDING, AP.REJECTED, TODAY - timedelta(days=3), TODAY) == "sent_back"

    def test_late_is_open_and_dated_before_today(self):
        assert trigger_for(ST.OVERDUE, AP.NONE, TODAY - timedelta(days=1), TODAY) == "late"
        assert trigger_for(ST.PENDING, AP.NONE, TODAY - timedelta(days=1), TODAY) == "late"

    def test_todays_open_chore_and_finished_chores_are_neither(self):
        assert trigger_for(ST.PENDING, AP.NONE, TODAY, TODAY) is None
        assert trigger_for(ST.COMPLETED, AP.NONE, TODAY - timedelta(days=1), TODAY) is None
        assert trigger_for(ST.COMPLETED, AP.REJECTED, TODAY, TODAY) is None
        assert trigger_for(ST.CANCELLED, AP.NONE, TODAY - timedelta(days=1), TODAY) is None


class TestPickCandidate:
    def test_nothing_to_offer(self):
        assert pick_candidate([]) is None

    def test_sent_back_wins_over_late(self):
        late, sent = cand("late", 1), cand("sent_back", 5)
        assert pick_candidate([late, sent]) is sent

    def test_the_most_recent_one_wins_within_a_kind(self):
        old, new = cand("late", 6), cand("late", 2)
        assert pick_candidate([old, new]) is new
        a, b = cand("sent_back", 4), cand("sent_back", 0)
        assert pick_candidate([a, b, cand("late", 1)]) is b

    def test_ties_are_broken_the_same_way_every_time(self):
        a, b = cand("late", 2), cand("late", 2)
        assert pick_candidate([a, b]) is pick_candidate([b, a])


class TestMayOffer:
    def test_a_fresh_teen_may_be_offered(self):
        assert may_offer(WED, []) is True

    def test_one_a_day(self):
        assert may_offer(WED, [(WED, "answered")]) is False

    def test_three_a_week(self):
        monday = WED - timedelta(days=2)
        two = [(monday, "answered"), (monday + timedelta(days=1), "answered")]
        assert may_offer(WED + timedelta(days=1), two) is True
        three = two + [(WED, "answered")]
        assert may_offer(WED + timedelta(days=1), three) is False
        # A new week starts clean.
        assert may_offer(monday + timedelta(days=7), three) is True

    def test_last_weeks_answers_do_not_count_toward_this_week(self):
        last_week = [(WED - timedelta(days=7 + i), "answered") for i in range(3)]
        assert may_offer(WED, last_week) is True

    def test_not_now_pauses_a_week(self):
        said_no = WED - timedelta(days=10)
        for gap in range(PAUSE_DAYS):
            assert may_offer(said_no + timedelta(days=gap), [(said_no, "dismissed")]) is False
        assert may_offer(said_no + timedelta(days=PAUSE_DAYS), [(said_no, "dismissed")]) is True

    def test_an_answer_does_not_pause(self):
        assert may_offer(WED, [(WED - timedelta(days=1), "answered")]) is True


class TestNote:
    def test_blank_becomes_none(self):
        assert normalize_note("other", None) is None
        assert normalize_note("other", "   \n ") is None
        assert normalize_note("too_hard", "  ") is None

    def test_trimmed_for_the_two_open_reasons(self):
        assert normalize_note("app_problem", "  the photo button does nothing ") == "the photo button does nothing"
        assert normalize_note("other", "x" * NOTE_MAX) == "x" * NOTE_MAX

    @pytest.mark.parametrize("reason", ["too_hard", "not_clear", "no_time", "not_fair", "forgot", None])
    def test_refused_for_every_other_reason(self, reason):
        with pytest.raises(ValueError):
            normalize_note(reason, "my brother never does his")

    def test_refused_when_too_long(self):
        with pytest.raises(ValueError):
            normalize_note("other", "x" * (NOTE_MAX + 1))
```

`tests/test_teen_checkin_service.py`:

```python
"""Jarvis teen check-in against the test DB. Dates derive from the family's today."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole
from app.services.progress_service import ProgressService
from app.services.teen_checkin_service import TeenCheckinService


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


async def _on(db, family, value=True):
    family.teen_checkin_enabled = value
    await db.commit()


async def _template(db, family_id, *, bonus=False, title="Take out the trash", title_es="Saca la basura", points=15):
    t = TaskTemplate(id=uuid4(), title=title, title_es=title_es, points=points, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=bonus, is_active=True, family_id=family_id)
    db.add(t)
    await db.commit()
    return t


async def _assign(db, user, template, day, status=AssignmentStatus.OVERDUE, approval=ApprovalStatus.NONE,
                  grade=None):
    a = TaskAssignment(family_id=template.family_id, template_id=template.id, assigned_to=user.id,
                       status=status, approval_status=approval, completion_grade=grade,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _count(db):
    return (await db.execute(select(func.count()).select_from(TeenCheckin))).scalar()


async def _past_row(db, teen, *, days_ago, outcome="answered"):
    db.add(TeenCheckin(family_id=teen.family_id, user_id=teen.id, assignment_id=None, trigger="late",
                       outcome=outcome, reason="forgot" if outcome == "answered" else None, days_late=1,
                       points=10, lang="en", created_at=datetime.now(timezone.utc) - timedelta(days=days_ago)))
    await db.commit()


class TestOffer:
    async def test_a_late_chore_is_offered(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        a = await _assign(db_session, test_teen_user, chore, today - timedelta(days=2))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert offer is not None and offer.assignment_id == a.id
        assert (offer.trigger, offer.title, offer.title_es, offer.points) == ("late", "Take out the trash", "Saca la basura", 15)
        assert await _count(db_session) == 0                       # reading the offer stores nothing

    async def test_a_sent_back_chore_wins_and_may_be_dated_today(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        back = await _assign(db_session, test_teen_user, chore, today, AssignmentStatus.PENDING,
                             ApprovalStatus.REJECTED, grade="missed")
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert offer.assignment_id == back.id and offer.trigger == "sent_back"

    async def test_undecided_and_off_families_get_nothing(self, db_session, test_family, test_teen_user):
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None      # NULL = undecided
        await _on(db_session, test_family, False)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_only_teens(self, db_session, test_family, test_child_user, test_parent_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        for user in (test_child_user, test_parent_user):
            await _assign(db_session, user, chore, today - timedelta(days=1))
            assert await TeenCheckinService.offer_for(db_session, user) is None

    async def test_what_is_never_a_candidate(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        bonus = await _template(db_session, test_family.id, bonus=True)
        teen = test_teen_user
        await _assign(db_session, teen, bonus, today - timedelta(days=1))                       # optional work
        await _assign(db_session, teen, chore, today - timedelta(days=1), AssignmentStatus.COMPLETED)
        await _assign(db_session, teen, chore, today - timedelta(days=1), AssignmentStatus.CANCELLED)
        await _assign(db_session, teen, chore, today, AssignmentStatus.PENDING)                 # today, not late
        await _assign(db_session, teen, chore, today - timedelta(days=14))                      # too old
        assert await TeenCheckinService.offer_for(db_session, teen) is None
        edge = await _assign(db_session, teen, chore, today - timedelta(days=13))               # 14th day back
        assert (await TeenCheckinService.offer_for(db_session, teen)).assignment_id == edge.id

    async def test_a_siblings_or_another_familys_chore_is_never_offered(self, db_session, test_family, test_teen_user, test_child_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_child_user, chore, today - timedelta(days=1))
        other = Family(name="Other", teen_checkin_enabled=True)
        db_session.add(other)
        await db_session.commit()
        theirs = await _template(db_session, other.id)
        # A row that names our teen but belongs to the other family must not leak in.
        db_session.add(TaskAssignment(family_id=other.id, template_id=theirs.id, assigned_to=test_teen_user.id,
                                      status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                                      assigned_date=today - timedelta(days=1),
                                      week_of=today - timedelta(days=today.weekday() + 7)))
        await db_session.commit()
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_a_chore_already_asked_about_is_not_offered_again(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        a = await _assign(db_session, test_teen_user, chore, today - timedelta(days=3))
        db_session.add(TeenCheckin(family_id=test_family.id, user_id=test_teen_user.id, assignment_id=a.id,
                                   trigger="late", outcome="answered", reason="forgot", days_late=1, points=15,
                                   lang="en", created_at=datetime.now(timezone.utc) - timedelta(days=2)))
        await db_session.commit()
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None     # still late, already asked
        fresh = await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        assert (await TeenCheckinService.offer_for(db_session, test_teen_user)).assignment_id == fresh.id

    async def test_a_recent_not_now_pauses_and_an_old_one_does_not(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))
        await _past_row(db_session, test_teen_user, days_ago=8, outcome="dismissed")
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is not None
        await _past_row(db_session, test_teen_user, days_ago=3, outcome="dismissed")
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None


class TestRecord:
    async def _offered(self, db, family, teen, **kw):
        await _on(db, family)
        today = await _today(db, family.id)
        chore = await _template(db, family.id, **kw)
        return await _assign(db, teen, chore, today - timedelta(days=2))

    async def test_an_answer_is_stored_without_the_title(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user, title="Clean Diego's room", points=25)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "not_fair", None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.family_id, row.user_id, row.assignment_id) == (test_family.id, test_teen_user.id, a.id)
        assert (row.trigger, row.outcome, row.reason, row.note) == ("late", "answered", "not_fair", None)
        assert (row.days_late, row.points, row.lang) == (2, 25, "en")
        stored = " ".join(str(v) for v in vars(row).values())
        assert "Diego" not in stored

    async def test_a_note_is_kept_for_an_open_reason_and_the_language_follows_the_teen(self, db_session, test_family, test_teen_user):
        test_teen_user.preferred_lang = "es-MX"
        await db_session.commit()
        a = await self._offered(db_session, test_family, test_teen_user)
        await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "app_problem", "  no abre la cámara ")
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.reason, row.note, row.lang) == ("app_problem", "no abre la cámara", "es")

    async def test_not_now_is_stored_and_nothing_more_is_offered_today(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        chore2 = await _template(db_session, test_family.id, title="Dishes")
        today = await _today(db_session, test_family.id)
        await _assign(db_session, test_teen_user, chore2, today - timedelta(days=1))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        assert await TeenCheckinService.record(db_session, test_teen_user, offer.assignment_id, "dismissed", None, None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.outcome, row.reason) == ("dismissed", None)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None
        assert offer.assignment_id != a.id                         # the more recent chore was the one offered

    async def test_after_an_answer_nothing_more_is_offered_today(self, db_session, test_family, test_teen_user):
        await self._offered(db_session, test_family, test_teen_user)
        today = await _today(db_session, test_family.id)
        other = await _template(db_session, test_family.id, title="Dishes")
        await _assign(db_session, test_teen_user, other, today - timedelta(days=1))
        offer = await TeenCheckinService.offer_for(db_session, test_teen_user)
        await TeenCheckinService.record(db_session, test_teen_user, offer.assignment_id, "answered", "forgot", None)
        assert await TeenCheckinService.offer_for(db_session, test_teen_user) is None

    async def test_saving_twice_is_harmless(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "forgot", None) is True
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "too_hard", None) is True
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert row.reason == "forgot"                              # the first answer stands

    async def test_only_the_current_offer_can_be_answered(self, db_session, test_family, test_teen_user, test_child_user):
        await _on(db_session, test_family)
        today = await _today(db_session, test_family.id)
        chore = await _template(db_session, test_family.id)
        older = await _assign(db_session, test_teen_user, chore, today - timedelta(days=5))
        await _assign(db_session, test_teen_user, chore, today - timedelta(days=1))               # the offer
        siblings = await _assign(db_session, test_child_user, chore, today - timedelta(days=1))
        not_late = await _assign(db_session, test_teen_user, chore, today, AssignmentStatus.PENDING)
        for bad in (older.id, siblings.id, not_late.id, uuid4()):
            assert await TeenCheckinService.record(db_session, test_teen_user, bad, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_another_familys_chore_cannot_be_answered(self, db_session, test_family, test_teen_user):
        await _on(db_session, test_family)
        other = Family(name="Other", teen_checkin_enabled=True)
        db_session.add(other)
        await db_session.commit()
        other_teen = User(email="otherteen@test.com", password_hash="x", name="Other Teen", role=UserRole.TEEN,
                          family_id=other.id, email_verified=True, points=0)
        db_session.add(other_teen)
        await db_session.commit()
        today = await _today(db_session, other.id)
        theirs = await _assign(db_session, other_teen, await _template(db_session, other.id), today - timedelta(days=1))
        assert await TeenCheckinService.record(db_session, test_teen_user, theirs.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_a_family_that_is_off_stores_nothing(self, db_session, test_family, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        await _on(db_session, test_family, None)
        assert await TeenCheckinService.record(db_session, test_teen_user, a.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0

    async def test_a_parent_or_child_can_never_store_a_row(self, db_session, test_family, test_parent_user, test_child_user, test_teen_user):
        a = await self._offered(db_session, test_family, test_teen_user)
        for user in (test_parent_user, test_child_user):
            assert await TeenCheckinService.record(db_session, user, a.id, "answered", "forgot", None) is False
        assert await _count(db_session) == 0


class TestCanChat:
    async def test_follows_the_plan(self, db_session, test_family):
        with patch("app.services.teen_checkin_service.family_tier_allows", new=AsyncMock(return_value=True)) as allows:
            assert await TeenCheckinService.can_chat(db_session, test_family.id) is True
        allows.assert_awaited_once_with(db_session, test_family.id, "ai_features")
        assert await TeenCheckinService.can_chat(db_session, test_family.id) is False             # free plan
```

- [ ] **Step 2: Run** both files — Expected: FAIL at import (`No module named app.services.teen_checkin_service`).

- [ ] **Step 3: Implement** `backend/app/services/teen_checkin_service.py`:

```python
"""Jarvis teen check-in: who is offered help, about which chore, how often —
and storing the one-tap answer.

Pure rules first (no DB), then the family-scoped queries. The offer is always
derived on the server, so a client can only answer the chore it was actually
offered. No LLM call here: the answer is a tap, the help is a ready-made tip.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.premium import family_tier_allows
from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole
from app.services.progress_service import ProgressService

REASONS = ("too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other")
# Free text is kept only where a tag says too little.
NOTE_REASONS = frozenset({"app_problem", "other"})
NOTE_MAX = 200
CANDIDATE_DAYS = 14   # a chore older than this is not worth asking about
MAX_PER_WEEK = 3      # Monday–Sunday, answers and dismissals alike
PAUSE_DAYS = 7        # "Not now" blocks offers for that day plus six


@dataclass(frozen=True)
class Candidate:
    assignment_id: UUID
    assigned_date: date
    trigger: str            # "late" | "sent_back"
    title: str
    title_es: Optional[str]
    points: int


def trigger_for(status, approval, assigned_date: date, today: date) -> Optional[str]:
    """Why this chore is worth a check-in, or None.

    sent_back — a parent rejected it and the app re-opened it for a redo
    (PENDING + REJECTED), whatever its date. late — still open and dated
    before today."""
    if status == AssignmentStatus.PENDING and approval == ApprovalStatus.REJECTED:
        return "sent_back"
    if status in (AssignmentStatus.PENDING, AssignmentStatus.OVERDUE) and assigned_date < today:
        return "late"
    return None


def pick_candidate(cands: list[Candidate]) -> Optional[Candidate]:
    """One chore per offer: a sent-back one first, else a late one; the most
    recently dated within the kind (the freshest in the teen's memory)."""
    sent_back = [c for c in cands if c.trigger == "sent_back"]
    pool = sent_back or [c for c in cands if c.trigger == "late"]
    if not pool:
        return None
    return max(pool, key=lambda c: (c.assigned_date, str(c.assignment_id)))


def may_offer(today: date, past: list[tuple[date, str]]) -> bool:
    """`past` — (family-local date, outcome) of the teen's earlier check-ins.
    One a day, MAX_PER_WEEK a week, and a dismissal pauses PAUSE_DAYS days."""
    week_start = today - timedelta(days=today.weekday())
    if any(day == today for day, _ in past):
        return False
    if sum(1 for day, _ in past if week_start <= day <= today) >= MAX_PER_WEEK:
        return False
    if any(outcome == "dismissed" and 0 <= (today - day).days < PAUSE_DAYS for day, outcome in past):
        return False
    return True


def normalize_note(reason: Optional[str], note: Optional[str]) -> Optional[str]:
    """Trimmed note, or None when blank. Raises ValueError for a note on a
    reason that takes none, or one longer than NOTE_MAX — never silently
    dropped: the teen was told where their words go."""
    text = (note or "").strip()
    if not text:
        return None
    if reason not in NOTE_REASONS:
        raise ValueError("a note is only kept for 'app_problem' and 'other'")
    if len(text) > NOTE_MAX:
        raise ValueError(f"a note is at most {NOTE_MAX} characters")
    return text


def _lang(raw: Optional[str]) -> str:
    return "es" if (raw or "").lower().startswith("es") else "en"


# ── Queries (family-scoped) ──────────────────────────────────────────────
class TeenCheckinService:
    @staticmethod
    async def can_chat(db: AsyncSession, family_id: UUID) -> bool:
        """Does the family's plan include the Jarvis conversation?"""
        return bool(await family_tier_allows(db, family_id, "ai_features"))

    @staticmethod
    async def _past(
        db: AsyncSession, family_id: UUID, user_id: UUID, today: date, tz: ZoneInfo,
    ) -> list[tuple[date, str]]:
        since = datetime.combine(today - timedelta(days=CANDIDATE_DAYS), datetime.min.time(), tzinfo=tz)
        rows = (await db.execute(
            select(TeenCheckin.created_at, TeenCheckin.outcome).where(
                TeenCheckin.family_id == family_id,
                TeenCheckin.user_id == user_id,
                TeenCheckin.created_at >= since,
            )
        )).all()
        return [(created.astimezone(tz).date(), outcome) for created, outcome in rows]

    @staticmethod
    async def _candidates(db: AsyncSession, family_id: UUID, user_id: UUID, today: date) -> list[Candidate]:
        asked = select(TeenCheckin.assignment_id).where(
            TeenCheckin.family_id == family_id,
            TeenCheckin.user_id == user_id,
            TeenCheckin.assignment_id.is_not(None),
        )
        rows = (await db.execute(
            select(
                TaskAssignment.id, TaskAssignment.assigned_date, TaskAssignment.status,
                TaskAssignment.approval_status, TaskTemplate.title, TaskTemplate.title_es, TaskTemplate.points,
            )
            .join(TaskTemplate, TaskTemplate.id == TaskAssignment.template_id)
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_to == user_id,
                TaskTemplate.is_bonus.is_(False),
                TaskAssignment.status.in_((AssignmentStatus.PENDING, AssignmentStatus.OVERDUE)),
                TaskAssignment.assigned_date > today - timedelta(days=CANDIDATE_DAYS),
                TaskAssignment.assigned_date <= today,
                TaskAssignment.id.not_in(asked),
            )
        )).all()
        out: list[Candidate] = []
        for row in rows:
            trigger = trigger_for(row.status, row.approval_status, row.assigned_date, today)
            if trigger:
                out.append(Candidate(row.id, row.assigned_date, trigger, row.title, row.title_es, int(row.points or 0)))
        return out

    @staticmethod
    async def offer_for(db: AsyncSession, user: User) -> Optional[Candidate]:
        """The chore Jarvis would ask this user about right now, or None.
        Read-only. Teens only, in a family that switched check-ins on."""
        if user.role != UserRole.TEEN:
            return None
        enabled = (await db.execute(
            select(Family.teen_checkin_enabled).where(Family.id == user.family_id)
        )).scalar()
        if enabled is not True:            # NULL (undecided) and False are both off
            return None
        today, tz = await ProgressService.family_today(db, user.family_id)
        if not may_offer(today, await TeenCheckinService._past(db, user.family_id, user.id, today, tz)):
            return None
        return pick_candidate(await TeenCheckinService._candidates(db, user.family_id, user.id, today))

    @staticmethod
    async def record(
        db: AsyncSession, user: User, assignment_id: UUID, outcome: str,
        reason: Optional[str], note: Optional[str],
    ) -> bool:
        """Store the teen's answer (or "not now") for the chore they were
        offered. False — and nothing stored — when that chore is not the
        current offer. Saving the same chore twice is harmless: the first
        answer stands."""
        family_id, user_id = user.family_id, user.id
        already = (await db.execute(
            select(TeenCheckin.id).where(
                TeenCheckin.family_id == family_id,
                TeenCheckin.user_id == user_id,
                TeenCheckin.assignment_id == assignment_id,
            )
        )).first()
        if already is not None:
            return True
        offer = await TeenCheckinService.offer_for(db, user)
        if offer is None or offer.assignment_id != assignment_id:
            return False
        today, _tz = await ProgressService.family_today(db, family_id)
        answered = outcome == "answered"
        await db.execute(
            pg_insert(TeenCheckin)
            .values(
                family_id=family_id,
                user_id=user_id,
                assignment_id=assignment_id,
                trigger=offer.trigger,
                outcome="answered" if answered else "dismissed",
                reason=reason if answered else None,
                note=normalize_note(reason, note) if answered else None,
                days_late=max(0, (today - offer.assigned_date).days),
                points=offer.points,
                lang=_lang(user.preferred_lang),
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_teen_checkins_family_user_assignment")
        )
        await db.commit()
        return True
```

- [ ] **Step 4: Run** `pytest tests/test_teen_checkin_rules.py tests/test_teen_checkin_service.py tests/test_teen_checkin_model.py` — Expected: PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) remove `TaskAssignment.family_id == family_id` from `_candidates`: `test_a_siblings_or_another_familys_chore_is_never_offered` fails. (b) `enabled is not True` → `enabled is False`: `test_undecided_and_off_families_get_nothing` fails. (c) remove the `offer.assignment_id != assignment_id` check: `test_only_the_current_offer_can_be_answered` fails. (d) `< PAUSE_DAYS` → `<= PAUSE_DAYS`: `test_not_now_pauses_a_week` fails. (e) remove `TaskAssignment.id.not_in(asked)`: `test_a_chore_already_asked_about_is_not_offered_again` fails. (f) make the `any(day == today …)` rule return nothing: `test_after_an_answer_nothing_more_is_offered_today` fails. Restore each.

- [ ] **Step 6: Commit** `feat(jarvis): teen check-in rules and service`

---

### Task 3: API

**Files:**
- Modify: `backend/app/api/routes/jarvis.py`
- Test: `backend/tests/test_teen_checkin_api.py`

**Interfaces:**
- Consumes: `TeenCheckinService.offer_for / record / can_chat`, `normalize_note`, `REASONS`.
- Produces:
  - `GET /api/jarvis/checkin` → `{"offer": {"assignment_id", "title", "title_es", "trigger", "days_late"} | null, "can_chat": bool}` — any signed-in role (non-teens get `offer: null`).
  - `POST /api/jarvis/checkin` body `{"assignment_id": UUID, "outcome": "answered"|"dismissed", "reason"?: str, "note"?: str}` → `200 {"saved": true, "can_chat": bool}`; `409` when the chore is not the current offer; `422` on an invalid body.

- [ ] **Step 1: Write the failing tests**

```python
"""Jarvis teen check-in endpoints."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.services.progress_service import ProgressService

URL = "/api/jarvis/checkin"


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _late_chore(db, family, teen, *, days=2, enabled=True):
    family.teen_checkin_enabled = enabled
    await db.commit()
    today, _tz = await ProgressService.family_today(db, family.id)
    template = TaskTemplate(id=uuid4(), title="Take out the trash", title_es="Saca la basura", points=15,
                            interval_days=1, assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=family.id)
    db.add(template)
    await db.commit()
    day = today - timedelta(days=days)
    a = TaskAssignment(family_id=family.id, template_id=template.id, assigned_to=teen.id,
                       status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


async def _count(db):
    return (await db.execute(select(func.count()).select_from(TeenCheckin))).scalar()


class TestGet:
    async def test_requires_auth(self, client):
        assert (await client.get(URL)).status_code in (401, 403)

    async def test_a_teen_gets_the_offer(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200
        assert r.json() == {
            "offer": {"assignment_id": str(a.id), "title": "Take out the trash", "title_es": "Saca la basura",
                      "trigger": "late", "days_late": 2},
            "can_chat": False,
        }

    async def test_no_offer_is_a_plain_null(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user, enabled=None)
        r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json() == {"offer": None, "can_chat": False}

    async def test_parents_and_children_get_no_offer(self, client, db_session, test_family, test_teen_user, test_parent_user, test_child_user):
        await _late_chore(db_session, test_family, test_teen_user)
        for email in ("parent@test.com", "child@test.com"):
            r = await client.get(URL, headers=await _login(client, email))
            assert r.status_code == 200 and r.json()["offer"] is None

    async def test_can_chat_follows_the_plan(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user)
        with patch("app.services.teen_checkin_service.family_tier_allows", new=AsyncMock(return_value=True)):
            r = await client.get(URL, headers=await _login(client, "teen@test.com"))
        assert r.json()["can_chat"] is True


class TestPost:
    async def test_requires_auth(self, client):
        r = await client.post(URL, json={"assignment_id": str(uuid4()), "outcome": "dismissed"})
        assert r.status_code in (401, 403)

    async def test_an_answer_is_saved(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "not_clear"},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200 and r.json() == {"saved": True, "can_chat": False}
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.outcome, row.reason, row.note, row.user_id) == ("answered", "not_clear", None, test_teen_user.id)

    async def test_a_note_is_saved_for_an_open_reason(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "other",
                                         "note": "  it is always my turn "},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 200
        assert (await db_session.execute(select(TeenCheckin.note))).scalar_one() == "it is always my turn"

    async def test_not_now_is_saved_and_the_offer_is_gone(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "dismissed"}, headers=headers)
        assert r.status_code == 200
        assert (await client.get(URL, headers=headers)).json()["offer"] is None

    async def test_bad_bodies_are_refused_and_store_nothing(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        base = {"assignment_id": str(a.id)}
        for body in (
            {**base, "outcome": "answered"},                                               # no reason
            {**base, "outcome": "answered", "reason": "because"},                          # unknown reason
            {**base, "outcome": "answered", "reason": "too_hard", "note": "my brother never does his"},
            {**base, "outcome": "answered", "reason": "other", "note": "x" * 201},
            {**base, "outcome": "dismissed", "reason": "forgot"},
            {**base, "outcome": "dismissed", "note": "hello"},
            {**base, "outcome": "maybe"},
            {"outcome": "dismissed"},                                                      # no assignment
        ):
            r = await client.post(URL, json=body, headers=headers)
            assert r.status_code == 422, body
        assert await _count(db_session) == 0

    async def test_a_chore_that_was_not_offered_is_a_conflict(self, client, db_session, test_family, test_teen_user):
        await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(uuid4()), "outcome": "answered", "reason": "forgot"},
                              headers=await _login(client, "teen@test.com"))
        assert r.status_code == 409
        assert await _count(db_session) == 0

    async def test_a_parent_cannot_answer_for_the_teen(self, client, db_session, test_family, test_teen_user, test_parent_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        r = await client.post(URL, json={"assignment_id": str(a.id), "outcome": "answered", "reason": "forgot"},
                              headers=await _login(client, "parent@test.com"))
        assert r.status_code == 409
        assert await _count(db_session) == 0

    async def test_a_double_tap_is_harmless(self, client, db_session, test_family, test_teen_user):
        a = await _late_chore(db_session, test_family, test_teen_user)
        headers = await _login(client, "teen@test.com")
        body = {"assignment_id": str(a.id), "outcome": "answered", "reason": "forgot"}
        assert (await client.post(URL, json=body, headers=headers)).status_code == 200
        assert (await client.post(URL, json=body, headers=headers)).status_code == 200
        assert await _count(db_session) == 1
```

- [ ] **Step 2: Run** `pytest tests/test_teen_checkin_api.py` — Expected: FAIL (404 on the route).

- [ ] **Step 3: Implement** — in `jarvis.py`: add `model_validator` to the pydantic import, `get_current_user` to the dependencies import, and append:

```python
# ── Teen check-in ─────────────────────────────────────────────────────────
# Jarvis offers a hand when a teen has a late or sent-back chore; the teen
# answers with one tap. No LLM call here, so no AI gate — the conversation
# that may follow is the ordinary (gated) teen chat.
from app.core.dependencies import get_current_user  # noqa: E402
from app.services.teen_checkin_service import (  # noqa: E402
    NOTE_MAX,
    TeenCheckinService,
    normalize_note,
)

CheckinReason = Literal["too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other"]


class CheckinOffer(BaseModel):
    assignment_id: UUID
    title: str
    title_es: Optional[str] = None
    trigger: str
    days_late: int


class CheckinOfferResponse(BaseModel):
    offer: Optional[CheckinOffer] = None
    can_chat: bool = False


class CheckinAnswer(BaseModel):
    assignment_id: UUID
    outcome: Literal["answered", "dismissed"]
    reason: Optional[CheckinReason] = None
    note: Optional[str] = Field(None, max_length=NOTE_MAX + 50)

    @model_validator(mode="after")
    def _consistent(self):
        if self.outcome == "answered":
            if self.reason is None:
                raise ValueError("an answer needs a reason")
            normalize_note(self.reason, self.note)          # raises ValueError → 422
        elif self.reason is not None or (self.note or "").strip():
            raise ValueError("a dismissal carries no reason and no note")
        return self


@router.get("/checkin", response_model=CheckinOfferResponse)
async def checkin_offer(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The chore Jarvis would ask this teen about now, if any. Read-only.
    Everyone but a teen in an opted-in family gets `offer: null`."""
    offer = await TeenCheckinService.offer_for(db, current_user)
    if offer is None:
        return CheckinOfferResponse()
    from app.services.progress_service import ProgressService

    today, _tz = await ProgressService.family_today(db, to_uuid_required(current_user.family_id))
    return CheckinOfferResponse(
        offer=CheckinOffer(
            assignment_id=offer.assignment_id,
            title=offer.title,
            title_es=offer.title_es,
            trigger=offer.trigger,
            days_late=max(0, (today - offer.assigned_date).days),
        ),
        can_chat=await TeenCheckinService.can_chat(db, to_uuid_required(current_user.family_id)),
    )


@router.post("/checkin")
async def checkin_answer(
    data: CheckinAnswer,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store the teen's one-tap answer (or "not now") for the offered chore."""
    saved = await TeenCheckinService.record(
        db, current_user, data.assignment_id, data.outcome, data.reason, data.note,
    )
    if not saved:
        raise HTTPException(status_code=409, detail="That task is not being asked about right now.")
    return {
        "saved": True,
        "can_chat": await TeenCheckinService.can_chat(db, to_uuid_required(current_user.family_id)),
    }
```

(Place the two imports with the module's other imports at the top; the block shows what is added.)

- [ ] **Step 4: Run** `pytest tests/test_teen_checkin_api.py tests/test_teen_checkin_service.py` — PASS. Then `pytest tests/test_ai_gating.py` (the gating regression suite must still pass). `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) remove the `normalize_note(...)` call from the validator: the "my brother…" and 201-character bodies are no longer 422 → `test_bad_bodies_are_refused_and_store_nothing` fails. (b) return 200 instead of raising 409: both conflict tests fail. Restore each.

- [ ] **Step 6: Commit** `feat(jarvis): teen check-in endpoints`

---

### Task 4: Operator summary

**Files:**
- Modify: `backend/app/services/admin/admin_read_service.py`, `backend/app/api/routes/admin/overview.py`
- Test: `backend/tests/test_teen_checkin_admin.py`

**Interfaces:**
- Produces: `AdminReadService.teen_checkin_summary(db, days: int, limit: int = 50, offset: int = 0) -> dict`; `GET /api/admin/teen-checkins?days=30&limit=50&offset=0` (`require_superadmin`) →

```json
{"days": 30, "answered": 0, "dismissed": 0, "families": 0, "teens": 0,
 "by_reason": {"too_hard": 0, "not_clear": 0, "no_time": 0, "not_fair": 0, "forgot": 0, "app_problem": 0, "other": 0},
 "by_kind": {"chore": 0, "app": 0, "other": 0},
 "by_trigger": {"late": 0, "sent_back": 0},
 "done_afterwards": 0,
 "notes": {"total": 0, "items": [{"created_at": "…", "reason": "other", "lang": "es", "note": "…"}]}}
```

- [ ] **Step 1: Write the failing tests**

```python
"""Operator view of the teen check-ins: counts across families, no identities."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models.family import Family
from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.models.user import User, UserRole

URL = "/api/admin/teen-checkins"
NOW = lambda: datetime.now(timezone.utc)  # noqa: E731


async def _teen(db, family, email):
    u = User(email=email, password_hash="x", name="Secret Name", role=UserRole.TEEN, family_id=family.id,
             email_verified=True, points=0)
    db.add(u)
    await db.commit()
    return u


async def _chore(db, family, teen, status):
    t = TaskTemplate(id=uuid4(), title="Secret Chore Title", points=10, interval_days=1,
                     assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True, family_id=family.id)
    db.add(t)
    await db.commit()
    day = NOW().date() - timedelta(days=1)
    a = TaskAssignment(family_id=family.id, template_id=t.id, assigned_to=teen.id, status=status,
                       approval_status=ApprovalStatus.NONE, assigned_date=day,
                       week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


def _row(family, teen, *, outcome="answered", reason="forgot", note=None, trigger="late", days_ago=1,
         assignment=None, lang="en"):
    return TeenCheckin(family_id=family.id, user_id=teen.id, assignment_id=assignment.id if assignment else None,
                       trigger=trigger, outcome=outcome, reason=reason if outcome == "answered" else None,
                       note=note, days_late=1, points=10, lang=lang, created_at=NOW() - timedelta(days=days_ago))


async def _seed(db, test_family):
    other = Family(name="Secret Family Name")
    db.add(other)
    await db.commit()
    t1 = await _teen(db, test_family, "t1@test.com")
    t2 = await _teen(db, other, "t2@test.com")
    done = await _chore(db, test_family, t1, AssignmentStatus.COMPLETED)
    still_open = await _chore(db, other, t2, AssignmentStatus.OVERDUE)
    db.add_all([
        _row(test_family, t1, reason="forgot", assignment=done),
        _row(test_family, t1, reason="not_fair", trigger="sent_back", days_ago=2),
        _row(test_family, t1, outcome="dismissed", days_ago=3),
        _row(other, t2, reason="app_problem", note="the photo button does nothing", assignment=still_open),
        _row(other, t2, reason="other", note="siempre me toca a mí", lang="es", days_ago=5),
        _row(other, t2, reason="too_hard", days_ago=40),                    # outside a 30-day window
    ])
    await db.commit()
    return other, t1, t2


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


class TestSummary:
    async def test_counts_span_families(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        r = await client.get(URL, params={"days": 30}, headers=superadmin_headers)
        assert r.status_code == 200
        body = r.json()
        assert (body["days"], body["answered"], body["dismissed"], body["families"], body["teens"]) == (30, 4, 1, 2, 2)
        assert body["by_reason"] == {"too_hard": 0, "not_clear": 0, "no_time": 0, "not_fair": 1, "forgot": 1,
                                     "app_problem": 1, "other": 1}
        assert body["by_kind"] == {"chore": 2, "app": 1, "other": 1}
        assert body["by_trigger"] == {"late": 3, "sent_back": 1}
        assert body["done_afterwards"] == 1
        for value in (body["answered"], body["families"], body["done_afterwards"], body["by_reason"]["forgot"]):
            assert isinstance(value, int)

    async def test_a_longer_window_reaches_older_rows(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        body = (await client.get(URL, params={"days": 90}, headers=superadmin_headers)).json()
        assert body["answered"] == 5 and body["by_reason"]["too_hard"] == 1

    async def test_notes_are_listed_newest_first_and_paged(self, client, db_session, superadmin_headers, test_family):
        await _seed(db_session, test_family)
        body = (await client.get(URL, params={"days": 30}, headers=superadmin_headers)).json()
        assert body["notes"]["total"] == 2
        assert [n["note"] for n in body["notes"]["items"]] == ["the photo button does nothing", "siempre me toca a mí"]
        assert body["notes"]["items"][1]["lang"] == "es" and body["notes"]["items"][0]["reason"] == "app_problem"
        page = (await client.get(URL, params={"days": 30, "limit": 1, "offset": 1}, headers=superadmin_headers)).json()
        assert [n["note"] for n in page["notes"]["items"]] == ["siempre me toca a mí"] and page["notes"]["total"] == 2

    async def test_nothing_in_the_answer_identifies_anyone(self, client, db_session, superadmin_headers, test_family):
        other, t1, t2 = await _seed(db_session, test_family)
        r = await client.get(URL, params={"days": 90}, headers=superadmin_headers)
        keys = set(_keys(r.json()))
        assert not ({"family_id", "user_id", "assignment_id", "id", "name", "email", "title", "family", "user"} & keys)
        assert set(r.json()["notes"]["items"][0]) == {"created_at", "reason", "lang", "note"}
        text = r.text
        for secret in (str(test_family.id), str(other.id), str(t1.id), str(t2.id), "Secret Name",
                       "Secret Family Name", "Secret Chore Title", "t1@test.com"):
            assert secret not in text

    async def test_an_empty_platform_reads_as_zeroes(self, client, superadmin_headers):
        body = (await client.get(URL, headers=superadmin_headers)).json()
        assert body["days"] == 30 and body["answered"] == 0 and body["notes"] == {"total": 0, "items": []}
        assert body["by_kind"] == {"chore": 0, "app": 0, "other": 0}

    async def test_bounds(self, client, superadmin_headers):
        for params in ({"days": 0}, {"days": 366}, {"limit": 0}, {"limit": 101}, {"offset": -1}):
            assert (await client.get(URL, params=params, headers=superadmin_headers)).status_code == 422


class TestAuthz:
    async def test_a_parent_gets_a_404(self, client, auth_headers):
        assert (await client.get(URL, headers=auth_headers)).status_code == 404

    async def test_anonymous_gets_no_data(self, client):
        assert (await client.get(URL)).status_code in (401, 403, 404)
```

- [ ] **Step 2: Run** `pytest tests/test_teen_checkin_admin.py` — Expected: FAIL (404 for the operator too).

- [ ] **Step 3: Implement**

`admin_read_service.py` — imports: `from app.models.teen_checkin import TeenCheckin` and `from app.services.teen_checkin_service import REASONS`; method:

```python
    @staticmethod
    async def teen_checkin_summary(
        db: AsyncSession, days: int, limit: int = 50, offset: int = 0,
    ) -> dict:
        """Why chores do not get done, across every family (Jarvis teen
        check-ins). Counts and anonymous notes ONLY: nothing here may name a
        family, a teen or a chore — the rows deliberately carry no title, and
        this query selects no id."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        recent = TeenCheckin.created_at >= since
        answered_rows = (TeenCheckin.outcome == "answered")

        outcomes = dict((await db.execute(
            select(TeenCheckin.outcome, func.count()).where(recent).group_by(TeenCheckin.outcome)
        )).all())
        reasons = dict((await db.execute(
            select(TeenCheckin.reason, func.count()).where(recent, answered_rows).group_by(TeenCheckin.reason)
        )).all())
        triggers = dict((await db.execute(
            select(TeenCheckin.trigger, func.count()).where(recent, answered_rows).group_by(TeenCheckin.trigger)
        )).all())
        families, teens = (await db.execute(
            select(func.count(func.distinct(TeenCheckin.family_id)), func.count(func.distinct(TeenCheckin.user_id)))
            .where(recent)
        )).one()
        done_afterwards = (await db.execute(
            select(func.count()).select_from(TeenCheckin)
            .join(TaskAssignment, TaskAssignment.id == TeenCheckin.assignment_id)
            .where(recent, answered_rows, TaskAssignment.status == AssignmentStatus.COMPLETED)
        )).scalar() or 0
        has_note = TeenCheckin.note.is_not(None)
        notes_total = (await db.execute(
            select(func.count()).select_from(TeenCheckin).where(recent, has_note)
        )).scalar() or 0
        notes = (await db.execute(
            select(TeenCheckin.created_at, TeenCheckin.reason, TeenCheckin.lang, TeenCheckin.note)
            .where(recent, has_note)
            .order_by(TeenCheckin.created_at.desc())
            .limit(limit).offset(offset)
        )).all()

        by_reason = {key: int(reasons.get(key, 0)) for key in REASONS}
        return {
            "days": int(days),
            "answered": int(outcomes.get("answered", 0)),
            "dismissed": int(outcomes.get("dismissed", 0)),
            "families": int(families or 0),
            "teens": int(teens or 0),
            "by_reason": by_reason,
            "by_kind": {
                "chore": sum(v for k, v in by_reason.items() if k not in ("app_problem", "other")),
                "app": by_reason["app_problem"],
                "other": by_reason["other"],
            },
            "by_trigger": {key: int(triggers.get(key, 0)) for key in ("late", "sent_back")},
            "done_afterwards": int(done_afterwards),
            "notes": {
                "total": int(notes_total),
                "items": [
                    {"created_at": created.isoformat(), "reason": reason, "lang": lang, "note": note}
                    for created, reason, lang, note in notes
                ],
            },
        }
```

`admin/overview.py`:

```python
@router.get("/teen-checkins")
async def teen_checkins(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _operator: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Jarvis teen check-ins across families: counts by reason + anonymous
    notes. No family, teen or chore is identified."""
    return await AdminReadService.teen_checkin_summary(db, days, limit, offset)
```

- [ ] **Step 4: Run** `pytest tests/test_teen_checkin_admin.py tests/test_admin_authz.py tests/test_admin_reads.py` — PASS. `ruff check app` clean.

- [ ] **Step 5: Mutation checks** — (a) add `"family_id": str(...)` to a note item: `test_nothing_in_the_answer_identifies_anyone` fails. (b) drop `recent` from the `reasons` query: `test_counts_span_families` fails. (c) replace `require_superadmin` with `get_current_user`: `test_a_parent_gets_a_404` fails. Restore each.

- [ ] **Step 6: Commit** `feat(jarvis): operator summary of teen check-ins`

---

### Task 5: Frontend — the teen card

**Files:**
- Create: `frontend/src/lib/checkin.ts`, `frontend/src/components/home/CheckinCard.astro`
- Modify: `frontend/src/components/home/KidHome.astro`, `frontend/src/pages/dashboard.astro`
- Test: `frontend/test/checkin.test.ts`, `frontend/test/checkin-card.test.ts`

**Interfaces:**
- Consumes: `GET/POST /api/jarvis/checkin` (Task 3).
- Produces (`lib/checkin.ts`): `REASONS`, `type Reason`, `NOTE_REASONS`, `NOTE_MAX`, `reasonLabel(reason, lang)`, `tipFor(reason, lang)`, `takesNote(reason)`, `type CheckinView = { assignmentId: string; title: string; canChat: boolean }`, `checkinView(resp: unknown, lang): CheckinView | null`, `answerBody(assignmentId, reason, note?)`, `dismissBody(assignmentId)`, `chatHref(title, reason, lang)`, `CHECKIN_COPY`.

- [ ] **Step 1: Write the failing tests**

`frontend/test/checkin.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
    NOTE_MAX, NOTE_REASONS, REASONS, answerBody, chatHref, checkinView, dismissBody, reasonLabel, takesNote, tipFor,
} from "../src/lib/checkin";

describe("reasons", () => {
    it("are the seven the backend accepts, in order", () => {
        expect([...REASONS]).toEqual(["too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other"]);
        expect([...NOTE_REASONS]).toEqual(["app_problem", "other"]);
        expect(NOTE_MAX).toBe(200);
    });
    it("every reason has a label and a tip in both languages", () => {
        for (const r of REASONS) {
            for (const lang of ["es", "en"] as const) {
                expect(reasonLabel(r, lang).length).toBeGreaterThan(3);
                expect(tipFor(r, lang).length).toBeGreaterThan(10);
            }
        }
        expect(reasonLabel("not_clear", "es")).toBe("No sé bien qué hacer");
        expect(reasonLabel("app_problem", "en")).toBe("The app won't let me");
        expect(tipFor("too_hard", "en")).toBe("Split it: set a 5-minute timer and do only the first part.");
        expect(tipFor("not_fair", "es")).toBe("Díselo a tus papás: en la app pueden volver a repartir las tareas de la semana.");
    });
    it("only the two open reasons take a note", () => {
        expect(REASONS.filter(takesNote)).toEqual(["app_problem", "other"]);
    });
});

describe("checkinView", () => {
    const offer = { assignment_id: "a1", title: "Take out the trash", title_es: "Saca la basura", trigger: "late", days_late: 2 };
    it("is null without an offer", () => {
        for (const v of [null, undefined, {}, { offer: null }, { offer: {} }, { offer: { title: "x" } }, "nope"]) {
            expect(checkinView(v, "es")).toBeNull();
        }
    });
    it("uses the Spanish title when there is one", () => {
        expect(checkinView({ offer, can_chat: true }, "es")).toEqual({ assignmentId: "a1", title: "Saca la basura", canChat: true });
        expect(checkinView({ offer, can_chat: false }, "en")).toEqual({ assignmentId: "a1", title: "Take out the trash", canChat: false });
        expect(checkinView({ offer: { ...offer, title_es: null } }, "es")?.title).toBe("Take out the trash");
    });
    it("treats a missing can_chat as no chat", () => {
        expect(checkinView({ offer }, "en")?.canChat).toBe(false);
    });
});

describe("request bodies", () => {
    it("an answer for a chore reason never carries a note", () => {
        expect(answerBody("a1", "too_hard", "my brother never does his")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "too_hard" });
    });
    it("an open reason carries a trimmed note, capped, or none when blank", () => {
        expect(answerBody("a1", "other", "  hi there ")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "other", note: "hi there" });
        expect(answerBody("a1", "app_problem", "   ")).toEqual({ assignment_id: "a1", outcome: "answered", reason: "app_problem" });
        expect((answerBody("a1", "other", "x".repeat(300)) as { note: string }).note).toHaveLength(200);
    });
    it("a dismissal is just that", () => {
        expect(dismissBody("a1")).toEqual({ assignment_id: "a1", outcome: "dismissed" });
    });
});

describe("chatHref", () => {
    it("opens Jarvis with a first message typed, in the teen's language", () => {
        const es = chatHref("Saca la basura", "not_clear", "es");
        expect(es.startsWith("/parent/jarvis?q=")).toBe(true);
        expect(decodeURIComponent(es.split("q=")[1])).toBe("Estoy atorado con «Saca la basura»: no sé bien qué hacer. ¿Me ayudas?");
        expect(decodeURIComponent(chatHref("Take out the trash", "too_hard", "en").split("q=")[1]))
            .toBe('I\'m stuck on "Take out the trash": it\'s too hard. Can you help?');
    });
    it("encodes a title with special characters", () => {
        const href = chatHref("Tidy & sweep?", "forgot", "en");
        expect(href).not.toContain("&");
        expect(decodeURIComponent(href.split("q=")[1])).toContain("Tidy & sweep?");
    });
});
```

`frontend/test/checkin-card.test.ts`:

```ts
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const path = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const read = (p: string) => readFileSync(path(p), "utf8");
const card = read("../src/components/home/CheckinCard.astro");
const home = read("../src/components/home/KidHome.astro");
const dash = read("../src/pages/dashboard.astro");

describe("CheckinCard", () => {
    it("has the three states, toggled with the hidden attribute", () => {
        for (const state of ["data-checkin-offer", "data-checkin-reasons", "data-checkin-help"]) {
            expect(card).toContain(state);
        }
        expect(card).toMatch(/data-checkin-reasons hidden/);
        expect(card).toMatch(/data-checkin-help hidden/);
        expect(card).not.toMatch(/class="[^"]*(?<![\w-])hidden(?![\w-])/);
    });
    it("asks in both languages and offers a way out", () => {
        expect(card).toContain("¿Atorado con");
        expect(card).toContain("Stuck on");
        expect(card).toContain("Sí, ayúdame");
        expect(card).toContain("Yes, help me");
        expect(card).toContain("Ahora no");
        expect(card).toContain("Not now");
    });
    it("renders one chip per reason from the shared list", () => {
        expect(card).toMatch(/REASONS\.map\(/);
        expect(card).toMatch(/data-checkin-reason=\{r\}/);
    });
    it("tells the teen where a note goes, and caps it", () => {
        expect(card).toContain("Tu nota llega al equipo de la app, sin tu nombre.");
        expect(card).toContain("Your note goes to the app's team, without your name.");
        expect(card).toMatch(/maxlength=\{NOTE_MAX\}/);
    });
    it("never promises that parents cannot see the answer", () => {
        expect(card).not.toMatch(/tus pap[aá]s no|your parents (won't|will not|can't|cannot)/i);
    });
    it("saves through the proxied Jarvis route, with a toast on failure", () => {
        expect(card).toMatch(/fetch\("\/api\/jarvis\/checkin"/);
        expect(card).toMatch(/method: "POST"/);
        expect(card).toMatch(/showToast\(/);
        expect(existsSync(path("../src/pages/api/jarvis/[...path].ts"))).toBe(true);
    });
    it("shows the chat button only when the plan has it", () => {
        expect(card).toMatch(/data-checkin-chat/);
        expect(card).toMatch(/hidden=\{!checkin\.canChat\}|canChat/);
        expect(card).toMatch(/chatHref\(/);
    });
    it("uses no native dialog and no emoji in a heading 1", () => {
        expect(card).not.toMatch(/\b(alert|confirm|prompt)\(/);
        expect(card).not.toMatch(/<h1/);
    });
});

describe("wiring", () => {
    it("the dashboard asks for an offer for teens only", () => {
        expect(dash).toMatch(/user\.role === "teen" \? apiFetch<any>\("\/api\/jarvis\/checkin", \{ token \}\) : none/);
        expect(dash).toMatch(/checkinView\(/);
        expect(dash).toMatch(/checkin=\{checkin\}/);
    });
    it("KidHome shows the card under the task deck, above the quest", () => {
        const deck = home.indexOf("<TaskDeck");
        const cardAt = home.indexOf("<CheckinCard");
        const quest = home.indexOf("<QuestCard");
        expect(deck).toBeGreaterThan(-1);
        expect(cardAt).toBeGreaterThan(deck);
        expect(quest).toBeGreaterThan(cardAt);
        expect(home).toMatch(/\{checkin && <CheckinCard checkin=\{checkin\} lang=\{lang\} \/>\}/);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/checkin.test.ts test/checkin-card.test.ts` — Expected: FAIL (cannot resolve `../src/lib/checkin`).

- [ ] **Step 3: Implement**

`frontend/src/lib/checkin.ts`:

```ts
/** Jarvis teen check-in — the only place its copy lives. The backend stores
 *  reason KEYS; labels, tips and the chat opener are here. */

export type Lang = "es" | "en";

export const REASONS = ["too_hard", "not_clear", "no_time", "not_fair", "forgot", "app_problem", "other"] as const;
export type Reason = (typeof REASONS)[number];

/** Free text is kept only where a tag says too little. */
export const NOTE_REASONS: readonly Reason[] = ["app_problem", "other"];
export const NOTE_MAX = 200;

type Entry = { es: string; en: string; tipEs: string; tipEn: string; chatEs: string; chatEn: string };

const COPY: Record<Reason, Entry> = {
    too_hard: {
        es: "Está muy difícil", en: "It's too hard",
        tipEs: "Divídela: pon 5 minutos en el reloj y haz solo la primera parte.",
        tipEn: "Split it: set a 5-minute timer and do only the first part.",
        chatEs: "está muy difícil", chatEn: "it's too hard",
    },
    not_clear: {
        es: "No sé bien qué hacer", en: "I'm not sure what to do",
        tipEs: "Pide a tu papá o mamá que te muestre una vez cómo debe quedar.",
        tipEn: 'Ask a parent to show you once what "done" looks like.',
        chatEs: "no sé bien qué hacer", chatEn: "I'm not sure what to do",
    },
    no_time: {
        es: "No tengo tiempo", en: "I don't have time",
        tipEs: "Pégala a algo que ya haces: antes de cenar o al llegar de la escuela.",
        tipEn: "Attach it to something you already do — before dinner, or right after school.",
        chatEs: "no tengo tiempo", chatEn: "I don't have time",
    },
    not_fair: {
        es: "No me parece justo", en: "It doesn't feel fair",
        tipEs: "Díselo a tus papás: en la app pueden volver a repartir las tareas de la semana.",
        tipEn: "Tell your parents — they can reshuffle the week's chores in the app.",
        chatEs: "no me parece justo", chatEn: "it doesn't feel fair",
    },
    forgot: {
        es: "Se me olvidó", en: "I forgot",
        tipEs: "Todavía puedes hacerla hoy. Activa las notificaciones para que no se te pase.",
        tipEn: "You can still do it today. Turn on notifications so it doesn't slip.",
        chatEs: "se me olvidó", chatEn: "I forgot",
    },
    app_problem: {
        es: "La app no me deja", en: "The app won't let me",
        tipEs: "Gracias. Lo vamos a revisar.", tipEn: "Thanks. We'll look into it.",
        chatEs: "la app no me deja", chatEn: "the app won't let me",
    },
    other: {
        es: "Otra cosa", en: "Something else",
        tipEs: "Gracias por decirnos.", tipEn: "Thanks for telling us.",
        chatEs: "es otra cosa", chatEn: "it's something else",
    },
};

export const reasonLabel = (r: Reason, lang: Lang): string => COPY[r][lang];
export const tipFor = (r: Reason, lang: Lang): string => (lang === "es" ? COPY[r].tipEs : COPY[r].tipEn);
export const takesNote = (r: Reason): boolean => NOTE_REASONS.includes(r);

export const CHECKIN_COPY = {
    question: { es: "¿Atorado con", en: "Stuck on" },
    yes: { es: "Sí, ayúdame", en: "Yes, help me" },
    notNow: { es: "Ahora no", en: "Not now" },
    pick: { es: "¿Qué pasa?", en: "What's going on?" },
    noteHint: { es: "Tu nota llega al equipo de la app, sin tu nombre.", en: "Your note goes to the app's team, without your name." },
    notePlaceholder: { es: "Cuéntanos (opcional)", en: "Tell us (optional)" },
    send: { es: "Enviar", en: "Send" },
    chat: { es: "Hablarlo con Jarvis", en: "Talk it through with Jarvis" },
    failed: { es: "No se pudo guardar. Intenta de nuevo.", en: "Could not save. Try again." },
} as const;

export type CheckinView = { assignmentId: string; title: string; canChat: boolean };

/** The card's view of GET /api/jarvis/checkin, or null when nothing is offered. */
export function checkinView(resp: unknown, lang: Lang): CheckinView | null {
    const offer = (resp as { offer?: Record<string, unknown> } | null)?.offer;
    if (!offer || typeof offer.assignment_id !== "string" || typeof offer.title !== "string") return null;
    const titleEs = typeof offer.title_es === "string" && offer.title_es ? offer.title_es : null;
    return {
        assignmentId: offer.assignment_id,
        title: lang === "es" && titleEs ? titleEs : offer.title,
        canChat: (resp as { can_chat?: unknown }).can_chat === true,
    };
}

export function answerBody(assignmentId: string, reason: Reason, note?: string | null) {
    const body: { assignment_id: string; outcome: "answered"; reason: Reason; note?: string } = {
        assignment_id: assignmentId, outcome: "answered", reason,
    };
    const text = (note ?? "").trim().slice(0, NOTE_MAX);
    if (takesNote(reason) && text) body.note = text;
    return body;
}

export const dismissBody = (assignmentId: string) => ({ assignment_id: assignmentId, outcome: "dismissed" as const });

/** Opens the teen's own Jarvis chat with a first message typed. Nothing
 *  reaches the AI until the teen sends it. */
export function chatHref(title: string, reason: Reason, lang: Lang): string {
    const text = lang === "es"
        ? `Estoy atorado con «${title}»: ${COPY[reason].chatEs}. ¿Me ayudas?`
        : `I'm stuck on "${title}": ${COPY[reason].chatEn}. Can you help?`;
    return `/parent/jarvis?q=${encodeURIComponent(text)}`;
}
```

`frontend/src/components/home/CheckinCard.astro`:

```astro
---
/**
 * Jarvis teen check-in card on the teen home: offer → reason → help.
 * One card, three states, no modal. The answer is one tap (that is what is
 * stored); the help is a ready-made tip, plus the teen's own Jarvis chat on
 * plans that have it. Never claims the answer is hidden from parents.
 */
import { buttonClass } from "../../lib/buttonClasses";
import { CHECKIN_COPY, NOTE_MAX, REASONS, reasonLabel, type CheckinView } from "../../lib/checkin";

interface Props {
    checkin: CheckinView;
    lang: "es" | "en";
}
const { checkin, lang } = Astro.props;
const c = CHECKIN_COPY;
---

<section data-checkin-card data-lang={lang} data-assignment={checkin.assignmentId} data-title={checkin.title}
         data-can-chat={checkin.canChat ? "1" : "0"}
         class="rounded-2xl border border-brand-ink/10 bg-white p-4 shadow-[var(--shadow-card)]">
    <h2 class="text-xs font-extrabold uppercase tracking-wider text-brand-ink-soft">Jarvis</h2>

    <div data-checkin-offer class="mt-2">
        <p class="font-bold text-brand-ink">
            <span aria-hidden="true">🤝 </span>{c.question[lang]} <span class="italic">{checkin.title}</span>?
        </p>
        <div class="mt-3 flex flex-wrap gap-2">
            <button type="button" data-checkin-yes class={buttonClass("secondary", "sm")}>{c.yes[lang]}</button>
            <button type="button" data-checkin-no
                    class="px-4 py-2 rounded-lg bg-brand-cream-deep text-brand-ink text-xs font-semibold hover:bg-brand-cream border border-brand-ink/15 transition-colors">
                {c.notNow[lang]}
            </button>
        </div>
    </div>

    <div data-checkin-reasons hidden class="mt-2">
        <p class="font-bold text-brand-ink">{c.pick[lang]}</p>
        <div class="mt-3 flex flex-wrap gap-2">
            {REASONS.map((r) => (
                <button type="button" data-checkin-reason={r}
                        class="px-3 py-2 rounded-full bg-brand-cream-deep text-brand-ink text-sm font-semibold border border-brand-ink/15 hover:bg-brand-cream transition-colors">
                    {reasonLabel(r, lang)}
                </button>
            ))}
        </div>
        <div data-checkin-note-block hidden class="mt-3">
            <textarea data-checkin-note rows="2" maxlength={NOTE_MAX} placeholder={c.notePlaceholder[lang]}
                      class="w-full rounded-lg border border-brand-ink/20 bg-white px-3 py-2 text-sm text-brand-ink focus:outline-none focus:ring-2 focus:ring-brand-sky"></textarea>
            <p class="mt-1 text-xs text-brand-ink-soft">{c.noteHint[lang]}</p>
            <button type="button" data-checkin-send class={`mt-2 ${buttonClass("secondary", "sm")}`}>{c.send[lang]}</button>
        </div>
    </div>

    <div data-checkin-help hidden class="mt-2">
        <p class="font-bold text-brand-ink" data-checkin-tip></p>
        <a data-checkin-chat hidden href="/parent/jarvis" class={`mt-3 inline-flex ${buttonClass("secondary", "sm")}`}>
            {c.chat[lang]}
        </a>
    </div>
</section>

<script>
    import { CHECKIN_COPY, answerBody, chatHref, dismissBody, takesNote, tipFor, type Reason } from "../../lib/checkin";
    import { showToast } from "../../lib/toast";

    const card = document.querySelector<HTMLElement>("[data-checkin-card]");
    if (card) {
        const lang = card.dataset.lang === "en" ? "en" : "es";
        const assignmentId = card.dataset.assignment ?? "";
        const title = card.dataset.title ?? "";
        const canChat = card.dataset.canChat === "1";
        const part = (name: string) => card.querySelector<HTMLElement>(`[data-checkin-${name}]`);
        const offer = part("offer"), reasons = part("reasons"), help = part("help");
        const noteBlock = part("note-block");
        const note = card.querySelector<HTMLTextAreaElement>("[data-checkin-note]");
        let busy = false;
        let picked: Reason | null = null;

        const save = async (body: unknown): Promise<boolean> => {
            if (busy) return false;
            busy = true;
            try {
                const r = await fetch("/api/jarvis/checkin", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                });
                if (r.ok) return true;
            } catch {
                /* fall through to the toast */
            } finally {
                busy = false;
            }
            showToast(CHECKIN_COPY.failed[lang], "error");
            return false;
        };

        const showHelp = (reason: Reason) => {
            reasons?.setAttribute("hidden", "");
            help?.removeAttribute("hidden");
            const tip = part("tip");
            if (tip) tip.textContent = tipFor(reason, lang);
            const chat = card.querySelector<HTMLAnchorElement>("[data-checkin-chat]");
            if (chat && canChat) {
                chat.href = chatHref(title, reason, lang);
                chat.removeAttribute("hidden");
            }
        };

        part("yes")?.addEventListener("click", () => {
            offer?.setAttribute("hidden", "");
            reasons?.removeAttribute("hidden");
        });
        part("no")?.addEventListener("click", async () => {
            if (await save(dismissBody(assignmentId))) card.remove();
        });
        card.querySelectorAll<HTMLButtonElement>("[data-checkin-reason]").forEach((chip) => {
            chip.addEventListener("click", async () => {
                const reason = chip.dataset.checkinReason as Reason;
                if (takesNote(reason)) {
                    // Saved on Send, so the note travels with the answer.
                    picked = reason;
                    noteBlock?.removeAttribute("hidden");
                    note?.focus();
                    return;
                }
                if (await save(answerBody(assignmentId, reason))) showHelp(reason);
            });
        });
        part("send")?.addEventListener("click", async () => {
            if (!picked) return;
            if (await save(answerBody(assignmentId, picked, note?.value))) showHelp(picked);
        });
    }
</script>
```

`KidHome.astro`: `import CheckinCard from "./CheckinCard.astro";`, `import type { CheckinView } from "../../lib/checkin";`, add to `Props` `/** Jarvis teen check-in; null = nothing offered (or not a teen). */ checkin: CheckinView | null;`, destructure `checkin`, and before the `QuestCard` line: `{checkin && <CheckinCard checkin={checkin} lang={lang} />}`.

`dashboard.astro`: `import { checkinView } from "../lib/checkin";`; add `{ data: checkinResp }` as the last element of the destructured `Promise.all` and, as the last call, `// Jarvis teen check-in. Teens only; apiFetch never throws; null → no card.` `user.role === "teen" ? apiFetch<any>("/api/jarvis/checkin", { token }) : none,`; then `const checkin = checkinView(checkinResp, lang);` and pass `checkin={checkin}` to `<KidHome>`.

Before writing, open `lib/buttonClasses.ts` and confirm `buttonClass("secondary", "sm")` is the call the quest hub card uses; match it exactly.

- [ ] **Step 4: Run** `npx vitest run test/checkin.test.ts test/checkin-card.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts test/contrast.test.ts` — PASS. `npm run check` — 0 errors. Then the whole suite `npx vitest run` — PASS.

- [ ] **Step 5: Mutation checks** — (a) in `answerBody` drop the `takesNote(reason) &&` guard: "an answer for a chore reason never carries a note" fails. (b) in `checkinView` return the English title always: "uses the Spanish title" fails. (c) remove `encodeURIComponent`: "encodes a title with special characters" fails. Restore each.

- [ ] **Step 6: Commit** `feat(jarvis): teen check-in card on the teen home`

---

### Task 6: Frontend — parents (opt-in card + settings)

**Files:**
- Modify: `frontend/src/pages/parent/index.astro`, `frontend/src/pages/parent/settings/family.astro`
- Test: `frontend/test/checkin-parent.test.ts`

**Interfaces:**
- Consumes: `family.teen_checkin_enabled` (`null | true | false`), `PATCH /api/families/me`, the oversight summary's `members[].role`.

- [ ] **Step 1: Write the failing test**

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const hub = read("../src/pages/parent/index.astro");
const settings = read("../src/pages/parent/settings/family.astro");

const ES = "Cuando una tarea se atrasa o la regresas, Jarvis le pregunta a tu adolescente qué pasó y le da una idea para destrabarse. El motivo que elige (y una nota corta si es un problema con la app) nos ayuda a mejorar la app; lo vemos sin nombres.";
const EN = "When a chore is late or you send it back, Jarvis asks your teen what happened and offers a way to get unstuck. The reason they pick (and a short note if it is a problem with the app) helps us improve the app; we see it without names.";

describe("parent hub — teen check-in opt-in card", () => {
    const banner = hub.match(/<div id="checkin-intro-banner"[\s\S]*?<\/div>\s*\)\}/)?.[0] ?? "";
    it("shows only to an undecided family that has a teen", () => {
        expect(hub).toMatch(/const hasTeen = \(oversightRes\.data\?\.members \?\? \[\]\)\.some\(\(k: any\) => String\(k\.role\)\.toLowerCase\(\) === "teen"\);/);
        expect(hub).toMatch(/\{family && family\.teen_checkin_enabled == null && hasTeen && \(/);
        expect(banner).not.toBe("");
    });
    it("explains what is stored and who sees it, in both languages", () => {
        expect(banner).toContain("Nuevo: Jarvis acompaña a tus adolescentes");
        expect(banner).toContain("New: Jarvis checks in with your teens");
        expect(banner).toContain(ES);
        expect(banner).toContain(EN);
    });
    it("has both answers and saves them as true / false", () => {
        expect(banner).toMatch(/id="checkin-intro-on"/);
        expect(banner).toMatch(/id="checkin-intro-off"/);
        expect(hub).toMatch(/JSON\.stringify\(\{ teen_checkin_enabled: on \}\)/);
        expect(hub).toMatch(/getElementById\("checkin-intro-on"\)\?\.addEventListener\("click", \(\) => checkinIntroDecide\(true\)\)/);
        expect(hub).toMatch(/getElementById\("checkin-intro-off"\)\?\.addEventListener\("click", \(\) => checkinIntroDecide\(false\)\)/);
        expect(hub).toMatch(/if \(r\.ok\) document\.getElementById\("checkin-intro-banner"\)\?\.remove\(\);/);
    });
});

describe("family settings — teen check-in checkbox", () => {
    const section = settings.match(/<section[^>]*id="teen-checkin-section"[\s\S]*?<\/section>/)?.[0] ?? "";
    it("sits right under the smart reminders section", () => {
        expect(section).not.toBe("");
        expect(settings.indexOf('id="smart-reminders-section"')).toBeLessThan(settings.indexOf('id="teen-checkin-section"'));
        expect(settings.indexOf('id="teen-checkin-section"')).toBeLessThan(settings.indexOf('id="modules-section"'));
    });
    it("is checked only when the family said yes", () => {
        const input = section.match(/<input[^>]*id="teen-checkin"[^>]*>/s)?.[0] ?? "";
        expect(input).toMatch(/type="checkbox"/);
        expect(input).toMatch(/checked=\{family\?\.teen_checkin_enabled === true\}/);
    });
    it("carries the same explanation as the hub card", () => {
        expect(section).toContain("Jarvis acompaña a tus adolescentes");
        expect(section).toContain("Jarvis checks in with your teens");
        expect(section).toContain(ES);
        expect(section).toContain(EN);
    });
    it("saves at once, toasts, and reverts on failure", () => {
        expect(settings).toMatch(/teen_checkin_enabled: input\.checked/);
        const script = settings.slice(settings.indexOf('getElementById("teen-checkin")'));
        expect(script).toMatch(/addEventListener\("change"/);
        expect(script).toMatch(/showToast\(/);
        expect(script).toMatch(/input\.checked = !input\.checked/);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/checkin-parent.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement**

`parent/index.astro` frontmatter, after `const family = familyRes.data;`:

```ts
// Jarvis teen check-in: the opt-in card is only for families with a teen.
const hasTeen = (oversightRes.data?.members ?? []).some((k: any) => String(k.role).toLowerCase() === "teen");
```

Markup, right after the quest intro banner block:

```astro
    {family && family.teen_checkin_enabled == null && hasTeen && (
        <div id="checkin-intro-banner" class="max-w-md mx-auto w-full mb-6 bg-brand-sky/10 border border-brand-sky/30 rounded-2xl p-5 shadow-[var(--shadow-card)]">
            <h2 class="font-bold text-brand-ink text-base mb-1">
                {lang === "es" ? "Nuevo: Jarvis acompaña a tus adolescentes" : "New: Jarvis checks in with your teens"}
            </h2>
            <p class="text-sm text-brand-ink-soft mb-3">
                {lang === "es"
                    ? "Cuando una tarea se atrasa o la regresas, Jarvis le pregunta a tu adolescente qué pasó y le da una idea para destrabarse. El motivo que elige (y una nota corta si es un problema con la app) nos ayuda a mejorar la app; lo vemos sin nombres."
                    : "When a chore is late or you send it back, Jarvis asks your teen what happened and offers a way to get unstuck. The reason they pick (and a short note if it is a problem with the app) helps us improve the app; we see it without names."}
            </p>
            <div class="flex flex-wrap gap-2">
                <button id="checkin-intro-on" class={buttonClass("secondary", "sm")}>
                    {lang === "es" ? "Activar" : "Turn on"}
                </button>
                <button id="checkin-intro-off"
                        class="px-4 py-2 rounded-lg bg-brand-cream-deep text-brand-ink text-xs font-semibold hover:bg-brand-cream border border-brand-ink/15 transition-colors">
                    {lang === "es" ? "Ahora no" : "Not now"}
                </button>
            </div>
        </div>
    )}
```

Script, in the same `<script>` as `questIntroDecide`:

```ts
    // Jarvis teen check-in opt-in: true turns it on, false is "not now" — either
    // way the family is no longer undecided, so the card never returns.
    const checkinIntroDecide = async (on: boolean) => {
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ teen_checkin_enabled: on }),
            });
            if (r.ok) document.getElementById("checkin-intro-banner")?.remove();
        } catch (e) {
            console.error("teen check-in opt-in decision failed:", e);
        }
    };
    document.getElementById("checkin-intro-on")?.addEventListener("click", () => checkinIntroDecide(true));
    document.getElementById("checkin-intro-off")?.addEventListener("click", () => checkinIntroDecide(false));
```

`parent/settings/family.astro`, after `#smart-reminders-section`:

```astro
    <section class="mt-4 bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border border-brand-ink/10 space-y-3" id="teen-checkin-section"
             data-saved={lang === "es" ? "Guardado." : "Saved."}
             data-error={lang === "es" ? "No se pudo guardar. Intenta de nuevo." : "Could not save. Try again."}>
        <h2 class="text-sm font-bold text-brand-ink">🤝 Jarvis</h2>
        <label class="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" id="teen-checkin" checked={family?.teen_checkin_enabled === true}
                   class="mt-0.5 h-5 w-5 rounded border-brand-ink/30 accent-brand-ink" />
            <span>
                <span class="block text-sm font-semibold text-brand-ink">
                    {lang === "es" ? "Jarvis acompaña a tus adolescentes" : "Jarvis checks in with your teens"}
                </span>
                <span class="block text-xs text-brand-ink-soft mt-1">
                    {lang === "es"
                        ? "Cuando una tarea se atrasa o la regresas, Jarvis le pregunta a tu adolescente qué pasó y le da una idea para destrabarse. El motivo que elige (y una nota corta si es un problema con la app) nos ayuda a mejorar la app; lo vemos sin nombres."
                        : "When a chore is late or you send it back, Jarvis asks your teen what happened and offers a way to get unstuck. The reason they pick (and a short note if it is a problem with the app) helps us improve the app; we see it without names."}
                </span>
            </span>
        </label>
    </section>
```

and a script after the smart-reminders script:

```astro
<script>
    import { showToast } from "../../../lib/toast";

    const section = document.getElementById("teen-checkin-section");
    const input = document.getElementById("teen-checkin") as HTMLInputElement | null;
    input?.addEventListener("change", async () => {
        if (!section) return;
        input.disabled = true;
        let ok = false;
        try {
            const r = await fetch("/api/families/me", {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ teen_checkin_enabled: input.checked }),
            });
            ok = r.ok;
        } catch {
            ok = false;
        }
        if (!ok) input.checked = !input.checked;
        showToast(ok ? (section.dataset.saved ?? "") : (section.dataset.error ?? ""), ok ? "success" : "error");
        input.disabled = false;
    });
</script>
```

- [ ] **Step 4: Run** `npx vitest run test/checkin-parent.test.ts test/smart-reminders-settings.test.ts test/quest-intro.test.ts test/parent-hub.test.ts test/visual-consistency.test.ts test/no-native-dialogs.test.ts` — PASS. `npm run check` — 0 errors.

- [ ] **Step 5: Commit** `feat(jarvis): parent opt-in card and settings switch for teen check-ins`

---

### Task 7: Frontend — operator page

**Files:**
- Create: `frontend/src/pages/admin/feedback.astro`
- Modify: `frontend/src/components/ui/AdminShell.astro` (nav item + `active` type)
- Test: `frontend/test/admin-feedback.test.ts`

**Interfaces:**
- Consumes: `GET /api/admin/teen-checkins?days=&limit=&offset=` (Task 4), fetched server-side with `apiFetch`.

- [ ] **Step 1: Write the failing test**

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(fileURLToPath(new URL(p, import.meta.url)), "utf8");
const page = read("../src/pages/admin/feedback.astro");
const shell = read("../src/components/ui/AdminShell.astro");

describe("operator console — teen check-ins", () => {
    it("is in the console navigation", () => {
        expect(shell).toMatch(/\{ key: "feedback", href: "\/admin\/feedback", label: "Teen check-ins" \}/);
        expect(shell).toMatch(/"audit" \| "feedback"/);
        expect(page).toMatch(/<AdminShell title="Teen check-ins" active="feedback">/);
    });
    it("reads the summary on the server with the operator's token", () => {
        expect(page).toMatch(/apiFetch<any>\(`\/api\/admin\/teen-checkins\?\$\{params\}`, \{ token \}\)/);
        expect(page).toMatch(/if \(!token\) return Astro\.redirect\("\/login"\);/);
        expect(page).not.toMatch(/<script/);
    });
    it("offers the two windows and keeps the choice when paging notes", () => {
        expect(page).toMatch(/const days = Astro\.url\.searchParams\.get\("days"\) === "90" \? 90 : 30;/);
        expect(page).toContain("/admin/feedback?days=30");
        expect(page).toContain("/admin/feedback?days=90");
        expect(page).toMatch(/new URLSearchParams\(Astro\.url\.searchParams\)/);
    });
    it("shows every count the summary has", () => {
        for (const field of ["answered", "dismissed", "families", "teens", "done_afterwards", "by_reason", "by_kind", "by_trigger", "notes"]) {
            expect(page).toContain(field);
        }
    });
    it("tells a failed load apart from an empty one", () => {
        expect(page).toMatch(/\{!result && \(/);
        expect(page).toContain("Could not load");
        expect(page).toContain("No notes in this window.");
    });
    it("never reaches for an identity", () => {
        expect(page).not.toMatch(/family_id|user_id|assignment_id|\.name\b|\.email\b|\/admin\/families\//);
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/admin-feedback.test.ts` — Expected: FAIL (file missing).

- [ ] **Step 3: Implement**

`AdminShell.astro`: add `"feedback"` to the `active` union (`… | "audit" | "feedback"`) and, after the audit item, `{ key: "feedback", href: "/admin/feedback", label: "Teen check-ins" },`.

`frontend/src/pages/admin/feedback.astro`:

```astro
---
import AdminShell from "@components/ui/AdminShell.astro";
import { apiFetch } from "../../lib/api";

const token = Astro.cookies.get("access_token")?.value;
if (!token) return Astro.redirect("/login");

const days = Astro.url.searchParams.get("days") === "90" ? 90 : 30;
const offset = Math.max(0, Number(Astro.url.searchParams.get("offset") ?? "0") || 0);
const LIMIT = 50;

const params = new URLSearchParams({ days: String(days), limit: String(LIMIT), offset: String(offset) });
// null = the call failed (see lib/api.ts); an empty platform is a real object of zeroes.
const { data: result } = await apiFetch<any>(`/api/admin/teen-checkins?${params}`, { token });

const REASON_LABELS: Record<string, string> = {
    too_hard: "Too hard", not_clear: "Not sure what to do", no_time: "No time", not_fair: "Not fair",
    forgot: "Forgot", app_problem: "App won't let me", other: "Something else",
};
const pct = (n: number, of: number) => (of > 0 ? `${Math.round((n / of) * 100)}%` : "—");
const pageHref = (newOffset: number) => {
    const p = new URLSearchParams(Astro.url.searchParams);
    p.set("days", String(days));
    p.set("offset", String(newOffset));
    return `/admin/feedback?${p}`;
};
const windowClass = (d: number) =>
    `rounded px-3 py-2 text-sm ${d === days ? "bg-slate-900 text-white" : "border border-slate-300 text-slate-700"}`;
---

<AdminShell title="Teen check-ins" active="feedback">
    <p class="mb-4 max-w-3xl text-sm text-slate-600">
        What teens answer when Jarvis asks about a late or sent-back chore, across every family that turned check-ins on.
        Counts and anonymous notes only: no family, teen or chore is shown here.
    </p>

    <div class="mb-6 flex items-center gap-2">
        <a href="/admin/feedback?days=30" class={windowClass(30)}>Last 30 days</a>
        <a href="/admin/feedback?days=90" class={windowClass(90)}>Last 90 days</a>
    </div>

    {!result && (
        <p class="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            Could not load the check-ins. The backend may be restarting.
        </p>
    )}

    {result && (
        <>
            <div class="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
                {[
                    ["Answered", result.answered],
                    ["Not now", result.dismissed],
                    ["Families", result.families],
                    ["Teens", result.teens],
                    ["Done afterwards", `${result.done_afterwards} (${pct(result.done_afterwards, result.answered)})`],
                ].map(([label, value]) => (
                    <div class="rounded border border-slate-200 bg-white p-3">
                        <div class="text-xs uppercase tracking-wide text-slate-500">{label}</div>
                        <div class="num mt-1 text-xl font-semibold">{value}</div>
                    </div>
                ))}
            </div>

            <div class="mb-6 grid gap-6 md:grid-cols-2">
                <div>
                    <h2 class="mb-2 text-sm font-semibold text-slate-700">Answers by reason</h2>
                    <table class="w-full border-collapse text-sm">
                        <tbody>
                            {Object.entries(result.by_reason as Record<string, number>).map(([key, n]) => (
                                <tr class="border-b border-slate-100">
                                    <td class="py-2">{REASON_LABELS[key] ?? key}</td>
                                    <td class="num py-2 text-right">{n}</td>
                                    <td class="num py-2 pl-3 text-right text-slate-500">{pct(n, result.answered)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                <div>
                    <h2 class="mb-2 text-sm font-semibold text-slate-700">By kind and trigger</h2>
                    <table class="w-full border-collapse text-sm">
                        <tbody>
                            {[
                                ["About the chore", result.by_kind.chore],
                                ["About the app", result.by_kind.app],
                                ["Something else", result.by_kind.other],
                                ["Chore was late", result.by_trigger.late],
                                ["Chore was sent back", result.by_trigger.sent_back],
                            ].map(([label, n]) => (
                                <tr class="border-b border-slate-100">
                                    <td class="py-2">{label}</td>
                                    <td class="num py-2 text-right">{n}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            <h2 class="mb-2 text-sm font-semibold text-slate-700">
                Notes <span class="num font-normal text-slate-500">({result.notes.total})</span>
            </h2>
            {result.notes.items.length === 0 && (
                <p class="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">No notes in this window.</p>
            )}
            {result.notes.items.length > 0 && (
                <table class="w-full border-collapse text-sm">
                    <thead>
                        <tr class="border-b border-slate-200 text-left text-slate-500">
                            <th class="py-2">When</th>
                            <th class="py-2">Reason</th>
                            <th class="py-2">Lang</th>
                            <th class="py-2">Note</th>
                        </tr>
                    </thead>
                    <tbody>
                        {result.notes.items.map((row: any) => (
                            <tr class="border-b border-slate-100 align-top">
                                <td class="num py-2 whitespace-nowrap">{String(row.created_at).slice(0, 10)}</td>
                                <td class="py-2 whitespace-nowrap">{REASON_LABELS[row.reason] ?? row.reason}</td>
                                <td class="py-2">{row.lang}</td>
                                <td class="py-2">{row.note}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            <div class="mt-4 flex gap-3 text-sm">
                {offset > 0 && <a class="underline" href={pageHref(Math.max(0, offset - LIMIT))}>Newer</a>}
                {offset + LIMIT < result.notes.total && <a class="underline" href={pageHref(offset + LIMIT)}>Older</a>}
            </div>
        </>
    )}
</AdminShell>
```

- [ ] **Step 4: Run** `npx vitest run test/admin-feedback.test.ts` and the whole suite `npx vitest run` — PASS. `npm run check` — 0 errors. `npm run build` — succeeds.

- [ ] **Step 5: Commit** `feat(jarvis): operator page for teen check-ins`

---

### Task 8: Privacy notice and docs

**Files:**
- Modify: `frontend/src/pages/privacidad.astro`, `docs/USER_GUIDE_EN.md`, `docs/USER_GUIDE_ES.md`, `CLAUDE.md`
- Test: `frontend/test/privacy-checkin.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const page = readFileSync(fileURLToPath(new URL("../src/pages/privacidad.astro", import.meta.url)), "utf8");

describe("privacy notice — teen check-ins", () => {
    it("is a new version", () => {
        expect(page).toContain('version: "v2 — 1 de octubre de 2026"');
        expect(page).toContain('version: "v2 — October 1, 2026"');
        expect(page).not.toContain("v1 — ");
    });
    it("says what is stored, who sees it and how to turn it off, in both languages", () => {
        expect(page).toContain("Acompañamiento de Jarvis para adolescentes");
        expect(page).toContain("solo si la madre, padre o tutor lo activa");
        expect(page).toContain("hasta 200 caracteres");
        expect(page).toContain("sin nombres");
        expect(page).toContain("Jarvis check-ins for teens");
        expect(page).toContain("only if the parent or guardian turns it on");
        expect(page).toContain("up to 200 characters");
        expect(page).toContain("without names");
    });
});
```

- [ ] **Step 2: Run** `npx vitest run test/privacy-checkin.test.ts` — Expected: FAIL.

- [ ] **Step 3: Implement**

`privacidad.astro`: versions → `"v2 — 1 de octubre de 2026"` / `"v2 — October 1, 2026"`. Append to section 3's `ps` (ES):

```
"Acompañamiento de Jarvis para adolescentes (opcional, solo si la madre, padre o tutor lo activa): cuando una tarea se atrasa o se regresa, la app pregunta al adolescente el motivo. Guardamos el motivo elegido de una lista y, únicamente cuando se trata de un problema con la app o de \"otra cosa\", una nota de hasta 200 caracteres. Usamos esta información de forma agregada y sin nombres para mejorar el servicio; no guardamos el título de la tarea. Estos registros forman parte de la exportación de datos de la familia y la función se puede desactivar en cualquier momento en Ajustes → Familia.",
```

and (EN):

```
"Jarvis check-ins for teens (optional, only if the parent or guardian turns it on): when a chore is late or sent back, the app asks the teen why. We store the reason picked from a list and, only when it is a problem with the app or \"something else\", a note of up to 200 characters. We use this information in aggregate and without names to improve the service; we do not store the chore's title. These records are part of the family's data export, and the feature can be turned off at any time in Settings → Family.",
```

`docs/USER_GUIDE_EN.md` — before the `---` that precedes `# Chapter 26`, add:

```markdown
## 25.5 Jarvis Check-ins for Teens

When a teen has a chore that is late, or one a parent sent back, Jarvis offers a hand on the teen's home screen: "Stuck on *Take out the trash*?"

- **Yes, help me** — the teen picks what is going on with one tap (too hard, not sure what to do, no time, not fair, forgot, the app won't let me, something else) and gets a short tip. On plans with AI, a button opens their own Jarvis chat with the first message already typed.
- **Not now** — the card goes away and Jarvis does not ask again for a week.

Jarvis asks at most once a day and three times a week, and never twice about the same chore.

> **For parents:** check-ins are off until you turn them on — a card on your home screen asks once, and the switch lives in **Settings → Family → Jarvis**. The reason your teen picks (and a short note, only for "the app won't let me" or "something else") helps us improve the app; we see it without names and without the chore's title. These records are included in your family's data export.
```

`docs/USER_GUIDE_ES.md` — the same before the `---` that precedes `# Capitulo 26`, in the file's unaccented style:

```markdown
## 25.5 Jarvis Acompana a los Adolescentes

Cuando un adolescente tiene una tarea atrasada, o una que un papa le regreso, Jarvis le ofrece ayuda en su pantalla de inicio: "¿Atorado con *Saca la basura*?"

- **Si, ayudame** — el adolescente elige con un toque que esta pasando (esta muy dificil, no se bien que hacer, no tengo tiempo, no me parece justo, se me olvido, la app no me deja, otra cosa) y recibe un consejo corto. En planes con IA, un boton abre su propio chat con Jarvis con el primer mensaje ya escrito.
- **Ahora no** — la tarjeta desaparece y Jarvis no vuelve a preguntar en una semana.

Jarvis pregunta como maximo una vez al dia y tres veces por semana, y nunca dos veces por la misma tarea.

> **Para papas:** esta funcion esta apagada hasta que la actives: una tarjeta en tu pantalla de inicio pregunta una sola vez, y el interruptor vive en **Ajustes → Familia → Jarvis**. El motivo que elige tu adolescente (y una nota corta, solo para "la app no me deja" u "otra cosa") nos ayuda a mejorar la app; lo vemos sin nombres y sin el titulo de la tarea. Estos registros se incluyen en la exportacion de datos de tu familia.
```

Add the matching table-of-contents entries if chapter 25's sub-sections are listed in each guide's TOC (follow whatever 25.4 does).

`CLAUDE.md` — append to the **Jarvis** row's notes:

```
**Teen check-in**: when a teen has a late or sent-back chore, a card on the teen home offers help (`teen_checkin_service.py`, `GET/POST /api/jarvis/checkin`, `CheckinCard.astro`; copy only in `frontend/src/lib/checkin.ts`). The teen answers with a one-tap reason; a ≤200-char note is kept ONLY for `app_problem`/`other` (enforced by the API, and again by CHECK constraints). The server re-derives the offer, so a client can only answer the chore it was offered. Limits: 1/day, 3/week, "Not now" pauses 7 days, each chore once, chores from the last 14 days. `families.teen_checkin_enabled` is three-state with NO default (NULL = undecided → off + one-time parent-hub card in families with a teen) — it stores a minor's answers for the product team, so never default it on. `teen_checkins` carries no chore title, and the operator summary (`GET /api/admin/teen-checkins`, `/admin/feedback`) must never return a family, teen or chore identity. No LLM call in the feature (the follow-up chat is the ordinary gated teen thread).
```

- [ ] **Step 4: Run** `npx vitest run` (whole suite) — PASS; `npm run build` — succeeds.

- [ ] **Step 5: Commit** `docs(jarvis): privacy notice v2, guides and CLAUDE.md for teen check-ins`

---

## After the tasks

1. Schema parity (scratch DB at migration head vs ORM): `python scripts/check_schema_parity.py`.
2. Final whole-branch review (one fresh reviewer, most capable model) with the Review Focus list; one fix pass, each fix RED→GREEN.
3. Push → PR → watch CI → merge explicitly (`gh pr merge N --merge`) → sync main → `./scripts/deploy-onprem.sh -y`.
4. Prod check in the demo family only (`b8312b5a-c9c0-469f-992f-8dbd412db4a7`, verified by id): mariana sees the hub card → Turn on; diego (teen) sees an offer → picks a reason → tip; reload shows no card; `GET /api/admin/teen-checkins` as a non-operator returns 404. Leave the demo family switched on.
