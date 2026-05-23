# Mandatory vs Gigs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make mandatory tasks award zero points (baseline duty) and convert bonus tasks ("gigs") into the only point-earning activity, gated by today's mandatory completion and parent approval.

**Architecture:** Reuse existing `task_templates.is_bonus` flag. A new alembic migration zeros all non-bonus template points, adds a CHECK constraint, adds `families.timezone`, and adds approval-tracking columns to `task_assignments`. Service-layer changes in `TaskAssignmentService.complete_assignment` skip point awards for mandatory and gate gig completions into a `PENDING` approval queue. A new `approve_gig` service + two parent-only routes credit points on approval. Frontend adds a lock badge on the assignment list and a `/parent/approvals` review page.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy async / Alembic / Astro 5 / Tailwind / Playwright

**Spec:** [`docs/superpowers/specs/2026-05-22-mandatory-vs-gigs-design.md`](../specs/2026-05-22-mandatory-vs-gigs-design.md)

---

## File Structure

**New files:**
- `backend/migrations/versions/2026_05_22_mandatory_zero_points_and_gigs.py` — Alembic migration
- `backend/tests/test_gig_gating.py` — service-layer guard + zero-point tests
- `backend/tests/test_gig_approval.py` — approval flow tests
- `backend/tests/test_migration_mandatory_zero.py` — migration assertions
- `frontend/src/pages/parent/approvals.astro` — parent approval queue page
- `frontend/src/pages/api/assignments/approve.ts` — Astro proxy for approve route
- `frontend/src/pages/api/assignments/pending-approvals.ts` — Astro proxy for queue listing
- `e2e-tests/tests/gigs.spec.ts` — Playwright E2E

**Modified files:**
- `backend/app/models/family.py` — add `timezone` column
- `backend/app/models/task_assignment.py` — add approval columns, `ApprovalStatus` enum
- `backend/app/models/point_transaction.py` — add `GIG_APPROVED` enum + factory
- `backend/app/schemas/task_assignment.py` — add fields to response, complete payload, approve payload
- `backend/app/services/task_assignment_service.py` — `complete_assignment` rewrite (split mandatory vs gig), new `approve_gig` + `list_pending_approvals`, `_user_local_today`, list enrichment
- `backend/app/services/points_service.py` — new `award_gig_points`
- `backend/app/api/routes/task_assignments.py` — proof_text on complete, two new routes
- `backend/app/services/family_service.py` — seed default gig pack on family create
- `frontend/src/pages/parent/assignments.astro` — render lock + approval badges, proof modal
- `frontend/src/pages/api/assignments/complete.ts` — forward `proof_text`

---

## Task 1: Migration — schema + zero mandatory points + seed default gigs

**Files:**
- Create: `backend/migrations/versions/2026_05_22_mandatory_zero_points_and_gigs.py`

- [ ] **Step 1: Write the migration file**

```python
"""mandatory zero points + gig approval columns

Revision ID: gigs_v1_approval
Revises: seed_sub_plans_v1
Create Date: 2026-05-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "gigs_v1_approval"
down_revision = "seed_sub_plans_v1"
branch_labels = None
depends_on = None


APPROVAL_STATUS = postgresql.ENUM(
    "none", "pending", "approved", "rejected",
    name="approval_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. families.timezone
    op.add_column(
        "families",
        sa.Column("timezone", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE families SET timezone = 'UTC' WHERE timezone IS NULL")
    op.alter_column("families", "timezone", nullable=False, server_default="UTC")

    # 2. zero out mandatory template points
    op.execute("UPDATE task_templates SET points = 0 WHERE is_bonus = false")
    op.create_check_constraint(
        "chk_mandatory_zero_points",
        "task_templates",
        "is_bonus = true OR points = 0",
    )

    # 3. approval_status enum + columns on task_assignments
    approval_status = postgresql.ENUM(
        "none", "pending", "approved", "rejected",
        name="approval_status",
    )
    approval_status.create(bind, checkfirst=True)

    op.add_column(
        "task_assignments",
        sa.Column(
            "approval_status",
            sa.Enum("none", "pending", "approved", "rejected", name="approval_status", create_type=False),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column("task_assignments", sa.Column("proof_text", sa.Text(), nullable=True))
    op.add_column(
        "task_assignments",
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assignments_approved_by_users",
        "task_assignments", "users",
        ["approved_by"], ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "task_assignments",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("task_assignments", sa.Column("approval_notes", sa.Text(), nullable=True))
    op.create_index(
        "idx_assignments_family_approval",
        "task_assignments",
        ["family_id", "approval_status"],
    )

    # 4. new transaction type value
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'gig_approved'")

    # 5. seed default gig pack per existing family
    seed_default_gig_pack(bind)


def downgrade() -> None:
    op.drop_index("idx_assignments_family_approval", table_name="task_assignments")
    op.drop_constraint("fk_assignments_approved_by_users", "task_assignments", type_="foreignkey")
    op.drop_column("task_assignments", "approval_notes")
    op.drop_column("task_assignments", "approved_at")
    op.drop_column("task_assignments", "approved_by")
    op.drop_column("task_assignments", "proof_text")
    op.drop_column("task_assignments", "approval_status")

    bind = op.get_bind()
    sa.Enum(name="approval_status").drop(bind, checkfirst=True)

    op.drop_constraint("chk_mandatory_zero_points", "task_templates", type_="check")
    op.drop_column("families", "timezone")


DEFAULT_GIGS = [
    ("Learn a topic + writeup", "Pick something new (podman, git, a recipe). Read up, then write 5-10 sentences on what you learned.", 30),
    ("Read book chapter + discuss", "Read a chapter, then sit with a parent to discuss the main idea.", 20),
    ("Plan next 3 days of meals", "Propose breakfasts, lunches, and dinners for the next 3 days. List groceries needed.", 25),
    ("Help with grocery shopping", "Help compile the list, go to the store, and help carry/put away.", 15),
    ("Cook family dinner", "Plan, cook, and serve a family dinner with parent supervision.", 25),
    ("Tech-help parent (15 min)", "Help a parent with a phone/computer task for at least 15 minutes.", 10),
]


def seed_default_gig_pack(bind):
    family_ids = bind.execute(sa.text("SELECT id FROM families")).scalars().all()
    for family_id in family_ids:
        # Skip if any of these titles already exist for the family
        existing = bind.execute(
            sa.text(
                "SELECT title FROM task_templates "
                "WHERE family_id = :fid AND title = ANY(:titles)"
            ),
            {"fid": family_id, "titles": [t[0] for t in DEFAULT_GIGS]},
        ).scalars().all()
        existing_set = set(existing)
        for title, description, points in DEFAULT_GIGS:
            if title in existing_set:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO task_templates "
                    "(id, title, description, points, interval_days, assignment_type, "
                    " is_bonus, is_active, family_id, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :title, :desc, :points, 7, 'auto', "
                    " true, true, :fid, NOW(), NOW())"
                ),
                {"title": title, "desc": description, "points": points, "fid": family_id},
            )
```

- [ ] **Step 2: Apply migration locally**

Run: `docker exec family_app_backend alembic upgrade head`
Expected: prints `INFO  [alembic.runtime.migration] Running upgrade seed_sub_plans_v1 -> gigs_v1_approval`

- [ ] **Step 3: Verify schema + data in psql**

Run:
```bash
docker exec family_app_db psql -U familyapp familyapp -c "\d task_assignments" | grep approval
docker exec family_app_db psql -U familyapp familyapp -c "SELECT title, points, is_bonus FROM task_templates WHERE is_bonus = false LIMIT 5;"
docker exec family_app_db psql -U familyapp familyapp -c "SELECT COUNT(*) FROM task_templates WHERE title='Cook family dinner';"
```
Expected:
- `approval_status`, `proof_text`, `approved_by`, `approved_at`, `approval_notes` columns visible
- All listed mandatory templates have `points = 0`
- Count = number of families (1 in dev demo, 1+ in prod)

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/versions/2026_05_22_mandatory_zero_points_and_gigs.py
git commit -m "feat(db): mandatory zero points + gig approval columns + default gig pack"
```

---

## Task 2: Model updates — Family.timezone, TaskAssignment approval fields, GIG_APPROVED txn type

**Files:**
- Modify: `backend/app/models/family.py` (add `timezone`)
- Modify: `backend/app/models/task_assignment.py` (add `ApprovalStatus` enum + 5 columns)
- Modify: `backend/app/models/point_transaction.py` (add enum value + factory)

- [ ] **Step 1: Add `timezone` to Family model**

In `backend/app/models/family.py`, locate the column list inside `class Family(Base):`. Add after the existing `name` column:

```python
timezone = Column(String(64), nullable=False, default="UTC", server_default="UTC")
```

Ensure `String` is imported from `sqlalchemy`.

- [ ] **Step 2: Add `ApprovalStatus` enum + columns to TaskAssignment**

In `backend/app/models/task_assignment.py`, after the `AssignmentStatus` enum (around line 35), add:

```python
class ApprovalStatus(str, enum.Enum):
    """Gig approval lifecycle."""
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
```

Inside `class TaskAssignment(Base):`, after the existing `status` column block (around line 75), add:

```python
    approval_status = Column(
        SQLEnum(
            ApprovalStatus,
            values_callable=lambda x: [e.value for e in x],
            name="approval_status",
        ),
        nullable=False,
        default=ApprovalStatus.NONE,
        server_default="none",
        index=True,
    )
    proof_text = Column(Text, nullable=True)
    approved_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approval_notes = Column(Text, nullable=True)
```

Ensure `Text` is in the `sqlalchemy` import line.

- [ ] **Step 3: Add `GIG_APPROVED` to TransactionType and a factory**

In `backend/app/models/point_transaction.py`, locate `class TransactionType(str, Enum):` and add after `BONUS`:

```python
    GIG_APPROVED = "gig_approved"  # Points credited after parent approves a gig
```

Then after the existing `create_assignment_completion` classmethod, add:

```python
    @classmethod
    def create_gig_approval(cls, user_id, assignment_id, points: int, balance_before: int):
        return cls(
            type=TransactionType.GIG_APPROVED,
            user_id=user_id,
            assignment_id=assignment_id,
            points=points,
            balance_before=balance_before,
            balance_after=balance_before + points,
            description=f"Gig approved — earned {points} points",
        )
```

- [ ] **Step 4: Sanity-check imports load**

Run: `docker exec family_app_backend python -c "from app.models.task_assignment import ApprovalStatus; from app.models.point_transaction import TransactionType; print(ApprovalStatus.PENDING, TransactionType.GIG_APPROVED)"`
Expected: `ApprovalStatus.PENDING TransactionType.GIG_APPROVED` (no traceback)

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/family.py backend/app/models/task_assignment.py backend/app/models/point_transaction.py
git commit -m "feat(models): ApprovalStatus enum, gig approval fields, family timezone"
```

---

## Task 3: Schemas — proof_text + approval payloads

**Files:**
- Modify: `backend/app/schemas/task_assignment.py`

- [ ] **Step 1: Add schemas**

In `backend/app/schemas/task_assignment.py`, after the existing response schema (search for `class TaskAssignmentWithDetails`), add at file bottom:

```python
class CompleteAssignmentRequest(BaseModel):
    proof_text: Optional[str] = Field(None, max_length=4000)


class ApprovalDecision(BaseModel):
    approve: bool
    notes: Optional[str] = Field(None, max_length=2000)


class GigApprovalRow(BaseModel):
    assignment_id: UUID
    template_id: UUID
    template_title: str
    points: int
    assigned_to: UUID
    assigned_to_name: str
    completed_at: datetime
    proof_text: Optional[str] = None

    model_config = {"from_attributes": True}
```

Also extend the response model — find `class TaskAssignmentWithDetails(...)` and add (in field block):

```python
    is_locked: bool = False
    approval_status: str = "none"
    proof_text: Optional[str] = None
```

Ensure `from typing import Optional` and pydantic `Field`, plus `from uuid import UUID` and `from datetime import datetime` imports exist at top of the file.

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/task_assignment.py
git commit -m "feat(schemas): proof_text on complete, approval decision, gig row"
```

---

## Task 4: Service helper — local today date in family timezone

**Files:**
- Modify: `backend/app/services/task_assignment_service.py`
- Test: `backend/tests/test_gig_gating.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_gig_gating.py`:

```python
"""Gig gating + zero-point mandatory tests."""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_template import TaskTemplate, AssignmentType
from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.point_transaction import PointTransaction
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ForbiddenException
from sqlalchemy import select, func


@pytest.mark.asyncio
async def test_local_today_returns_family_tz(db_session: AsyncSession, demo_family, demo_child):
    """Helper computes today in family timezone."""
    demo_family.timezone = "America/Mexico_City"
    await db_session.commit()

    result = await TaskAssignmentService._user_local_today(db_session, demo_child.id)

    assert isinstance(result, date)
```

- [ ] **Step 2: Run test, confirm it fails**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py::test_local_today_returns_family_tz -v`
Expected: FAIL with `AttributeError: type object 'TaskAssignmentService' has no attribute '_user_local_today'`

- [ ] **Step 3: Implement helper**

In `backend/app/services/task_assignment_service.py`, near the top of the class add:

```python
    @staticmethod
    async def _user_local_today(db: AsyncSession, user_id: UUID) -> date:
        """Return today's date in the user's family timezone."""
        from zoneinfo import ZoneInfo
        from app.services.base_service import get_user_by_id
        user = await get_user_by_id(db, user_id)
        tz_name = (user.family.timezone if user.family else None) or "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        return datetime.now(tz).date()
```

Ensure `from datetime import date, datetime` is at top of file.

- [ ] **Step 4: Verify test passes**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py::test_local_today_returns_family_tz -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/test_gig_gating.py
git commit -m "feat(service): _user_local_today helper using family timezone"
```

---

## Task 5: complete_assignment — split mandatory vs gig

**Files:**
- Modify: `backend/app/services/task_assignment_service.py:570-626`
- Test: `backend/tests/test_gig_gating.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_gig_gating.py`:

```python
@pytest.mark.asyncio
async def test_mandatory_completion_awards_no_points(
    db_session, demo_family, demo_child, mandatory_template_factory,
):
    template = await mandatory_template_factory(family=demo_family, points=0)
    assignment = TaskAssignment(
        id=uuid4(),
        template_id=template.id,
        assigned_to=demo_child.id,
        family_id=demo_family.id,
        assigned_date=date.today(),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(assignment)
    await db_session.commit()

    before = demo_child.points
    result = await TaskAssignmentService.complete_assignment(
        db_session, assignment.id, demo_family.id, demo_child.id, proof_text=None,
    )

    await db_session.refresh(demo_child)
    assert result.status == AssignmentStatus.COMPLETED
    assert result.approval_status == ApprovalStatus.NONE
    assert demo_child.points == before

    count = await db_session.scalar(
        select(func.count()).select_from(PointTransaction).where(PointTransaction.user_id == demo_child.id)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_gig_locked_when_mandatory_pending(
    db_session, demo_family, demo_child,
    mandatory_template_factory, gig_template_factory,
):
    mandatory = await mandatory_template_factory(family=demo_family)
    gig = await gig_template_factory(family=demo_family, points=20)

    today = date.today()
    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mandatory.id, assigned_to=demo_child.id,
            family_id=demo_family.id, assigned_date=today, status=AssignmentStatus.PENDING,
        ),
        gig_assignment := TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=demo_child.id,
            family_id=demo_family.id, assigned_date=today, status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    with pytest.raises(ForbiddenException, match="mandatory"):
        await TaskAssignmentService.complete_assignment(
            db_session, gig_assignment.id, demo_family.id, demo_child.id,
            proof_text="did the gig",
        )


@pytest.mark.asyncio
async def test_gig_unlocked_completes_pending(
    db_session, demo_family, demo_child, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=20)
    today = date.today()
    assignment = TaskAssignment(
        id=uuid4(), template_id=gig.id, assigned_to=demo_child.id,
        family_id=demo_family.id, assigned_date=today, status=AssignmentStatus.PENDING,
    )
    db_session.add(assignment)
    await db_session.commit()

    before = demo_child.points
    result = await TaskAssignmentService.complete_assignment(
        db_session, assignment.id, demo_family.id, demo_child.id,
        proof_text="learned about rootless podman storage",
    )
    await db_session.refresh(demo_child)

    assert result.status == AssignmentStatus.COMPLETED
    assert result.approval_status == ApprovalStatus.PENDING
    assert result.proof_text == "learned about rootless podman storage"
    assert demo_child.points == before  # not yet credited
```

Fixtures referenced (`mandatory_template_factory`, `gig_template_factory`) — add to `backend/tests/conftest.py`:

```python
import pytest_asyncio
from uuid import uuid4
from app.models.task_template import TaskTemplate, AssignmentType

@pytest_asyncio.fixture
async def mandatory_template_factory(db_session):
    async def _make(*, family, points: int = 0, title: str = "Brush teeth"):
        t = TaskTemplate(
            id=uuid4(), title=title, points=points, interval_days=1,
            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
            family_id=family.id,
        )
        db_session.add(t)
        await db_session.commit()
        return t
    return _make

@pytest_asyncio.fixture
async def gig_template_factory(db_session):
    async def _make(*, family, points: int = 20, title: str = "Learn topic"):
        t = TaskTemplate(
            id=uuid4(), title=title, points=points, interval_days=7,
            assignment_type=AssignmentType.AUTO, is_bonus=True, is_active=True,
            family_id=family.id,
        )
        db_session.add(t)
        await db_session.commit()
        return t
    return _make
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py -v`
Expected: FAIL — current `complete_assignment` does not accept `proof_text`, awards points for mandatory, does not set `approval_status`.

- [ ] **Step 3: Rewrite `complete_assignment`**

In `backend/app/services/task_assignment_service.py`, replace the existing `complete_assignment` method (lines ~569-626) with:

```python
    @staticmethod
    async def complete_assignment(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        user_id: UUID,
        proof_text: Optional[str] = None,
    ) -> TaskAssignment:
        """
        Mark an assignment as completed.

        Mandatory (is_bonus=false): completes silently, awards no points.
        Gig (is_bonus=true): requires all today's mandatory done first, requires
        proof_text, and enters PENDING approval state. Points are credited only
        when a parent approves via approve_gig().
        """
        assignment = await TaskAssignmentService.get_assignment(
            db, assignment_id, family_id
        )

        if not assignment.can_complete:
            raise ValidationException(
                f"Assignment cannot be completed. Current status: {assignment.status.value}"
            )

        if assignment.assigned_to != user_id:
            raise ForbiddenException(
                "Only the assigned user can complete this assignment"
            )

        template = assignment.template

        if template.is_bonus:
            # Gig path
            all_required_done = await TaskAssignmentService.check_all_required_done_today(
                db, user_id, family_id, assignment.assigned_date
            )
            if not all_required_done:
                raise ForbiddenException(
                    "Complete today's mandatory tasks before claiming a gig"
                )

            if not proof_text or not proof_text.strip():
                raise ValidationException("Gigs require proof text describing what you did")

            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.utcnow()
            assignment.approval_status = ApprovalStatus.PENDING
            assignment.proof_text = proof_text.strip()
        else:
            # Mandatory path — silent, no points, no approval
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.utcnow()
            # approval_status stays NONE; no PointTransaction row

        await db.commit()
        await db.refresh(assignment)
        return assignment
```

Add imports at top of file if missing: `from app.models.task_assignment import ApprovalStatus`, `from typing import Optional`.

- [ ] **Step 4: Run tests, confirm they pass**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/test_gig_gating.py backend/tests/conftest.py
git commit -m "feat(service): mandatory completes silently, gig enters PENDING approval"
```

---

## Task 6: approve_gig service + list_pending_approvals

**Files:**
- Modify: `backend/app/services/task_assignment_service.py`
- Modify: `backend/app/services/points_service.py`
- Test: `backend/tests/test_gig_approval.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_gig_approval.py`:

```python
"""Gig approval flow."""
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
from app.models.point_transaction import PointTransaction, TransactionType
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException


async def _make_pending_gig(db_session, family, child, template):
    assignment = TaskAssignment(
        id=uuid4(), template_id=template.id, assigned_to=child.id,
        family_id=family.id, assigned_date=date.today(),
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.PENDING,
        proof_text="did the thing",
    )
    db_session.add(assignment)
    await db_session.commit()
    return assignment


@pytest.mark.asyncio
async def test_parent_approves_gig_credits_points(
    db_session, demo_family, demo_parent, demo_child, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=25)
    assignment = await _make_pending_gig(db_session, demo_family, demo_child, gig)
    before = demo_child.points

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, demo_family.id, demo_parent.id,
        approve=True, notes="great writeup",
    )

    await db_session.refresh(demo_child)
    await db_session.refresh(assignment)
    assert assignment.approval_status == ApprovalStatus.APPROVED
    assert demo_child.points == before + 25

    txn = await db_session.scalar(
        select(PointTransaction).where(PointTransaction.user_id == demo_child.id)
    )
    assert txn.type == TransactionType.GIG_APPROVED
    assert txn.points == 25


@pytest.mark.asyncio
async def test_parent_rejects_gig_no_credit(
    db_session, demo_family, demo_parent, demo_child, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=25)
    assignment = await _make_pending_gig(db_session, demo_family, demo_child, gig)
    before = demo_child.points

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, demo_family.id, demo_parent.id,
        approve=False, notes="no proof of conclusions",
    )
    await db_session.refresh(demo_child)
    await db_session.refresh(assignment)
    assert assignment.approval_status == ApprovalStatus.REJECTED
    assert demo_child.points == before
    count = await db_session.scalar(select(func.count()).select_from(PointTransaction))
    assert count == 0


@pytest.mark.asyncio
async def test_non_parent_cannot_approve(
    db_session, demo_family, demo_child, demo_teen, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=25)
    assignment = await _make_pending_gig(db_session, demo_family, demo_child, gig)

    with pytest.raises(ForbiddenException):
        await TaskAssignmentService.approve_gig(
            db_session, assignment.id, demo_family.id, demo_teen.id,
            approve=True, notes=None,
        )


@pytest.mark.asyncio
async def test_double_approve_conflicts(
    db_session, demo_family, demo_parent, demo_child, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=25)
    assignment = await _make_pending_gig(db_session, demo_family, demo_child, gig)

    await TaskAssignmentService.approve_gig(
        db_session, assignment.id, demo_family.id, demo_parent.id,
        approve=True, notes=None,
    )
    with pytest.raises(ValidationException, match="already"):
        await TaskAssignmentService.approve_gig(
            db_session, assignment.id, demo_family.id, demo_parent.id,
            approve=True, notes=None,
        )


@pytest.mark.asyncio
async def test_list_pending_approvals_family_scoped(
    db_session, demo_family, demo_child, gig_template_factory,
):
    gig = await gig_template_factory(family=demo_family, points=10)
    await _make_pending_gig(db_session, demo_family, demo_child, gig)

    rows = await TaskAssignmentService.list_pending_approvals(db_session, demo_family.id)
    assert len(rows) == 1
    assert rows[0].approval_status == ApprovalStatus.PENDING
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_approval.py -v`
Expected: FAIL with `AttributeError: type object 'TaskAssignmentService' has no attribute 'approve_gig'`

- [ ] **Step 3: Implement `approve_gig` + `list_pending_approvals`**

In `backend/app/services/task_assignment_service.py`, add inside the class:

```python
    @staticmethod
    async def approve_gig(
        db: AsyncSession,
        assignment_id: UUID,
        family_id: UUID,
        parent_id: UUID,
        approve: bool,
        notes: Optional[str] = None,
    ) -> TaskAssignment:
        from app.models.user import User, UserRole  # local import to avoid cycles
        from app.services.points_service import PointsService

        # Verify parent is a parent in this family
        parent = await get_user_by_id(db, parent_id)
        if parent.family_id != family_id or parent.role != UserRole.PARENT:
            raise ForbiddenException("Only parents in this family can approve gigs")

        assignment = await TaskAssignmentService.get_assignment(db, assignment_id, family_id)

        if assignment.approval_status != ApprovalStatus.PENDING:
            raise ValidationException(
                f"Gig already decided (status: {assignment.approval_status.value})"
            )

        assignment.approved_by = parent_id
        assignment.approved_at = datetime.utcnow()
        assignment.approval_notes = notes

        if approve:
            assignment.approval_status = ApprovalStatus.APPROVED
            await PointsService.award_gig_points(
                db, assignment.assigned_to, assignment.id, assignment.template.points
            )
        else:
            assignment.approval_status = ApprovalStatus.REJECTED

        await db.commit()
        await db.refresh(assignment)
        return assignment

    @staticmethod
    async def list_pending_approvals(
        db: AsyncSession,
        family_id: UUID,
    ) -> list[TaskAssignment]:
        from sqlalchemy.orm import selectinload
        q = (
            select(TaskAssignment)
            .options(
                selectinload(TaskAssignment.template),
                selectinload(TaskAssignment.assignee),
            )
            .where(
                TaskAssignment.family_id == family_id,
                TaskAssignment.approval_status == ApprovalStatus.PENDING,
            )
            .order_by(TaskAssignment.completed_at.asc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())
```

If `TaskAssignment.assignee` relationship doesn't exist yet, use `selectinload(TaskAssignment.assigned_to_user)` — check the model. (If neither exists, add `assignee = relationship("User", foreign_keys=[assigned_to])` to the model and re-run.)

- [ ] **Step 4: Implement `PointsService.award_gig_points`**

In `backend/app/services/points_service.py`, after `award_points_for_task`, add:

```python
    @staticmethod
    async def award_gig_points(
        db: AsyncSession,
        user_id: UUID,
        assignment_id: UUID,
        points: int,
    ) -> PointTransaction:
        user = await get_user_by_id(db, user_id)
        transaction = PointTransaction.create_gig_approval(
            user_id=user_id,
            assignment_id=assignment_id,
            points=points,
            balance_before=user.points,
        )
        user.points += points
        db.add(transaction)
        # caller is responsible for commit
        return transaction
```

- [ ] **Step 5: Run tests, confirm they pass**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_approval.py -v`
Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/app/services/points_service.py backend/tests/test_gig_approval.py
git commit -m "feat(service): approve_gig credits points, list_pending_approvals queue"
```

---

## Task 7: List enrichment — is_locked + approval fields

**Files:**
- Modify: `backend/app/services/task_assignment_service.py` (list endpoints)
- Modify: `backend/app/api/routes/task_assignments.py:80-145` (week/today/get one response shaping)

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_gig_gating.py`:

```python
@pytest.mark.asyncio
async def test_list_marks_gigs_locked_when_mandatory_pending(
    db_session, demo_family, demo_child,
    mandatory_template_factory, gig_template_factory,
):
    mand = await mandatory_template_factory(family=demo_family)
    gig = await gig_template_factory(family=demo_family, points=20)
    today = date.today()
    db_session.add_all([
        TaskAssignment(
            id=uuid4(), template_id=mand.id, assigned_to=demo_child.id,
            family_id=demo_family.id, assigned_date=today, status=AssignmentStatus.PENDING,
        ),
        TaskAssignment(
            id=uuid4(), template_id=gig.id, assigned_to=demo_child.id,
            family_id=demo_family.id, assigned_date=today, status=AssignmentStatus.PENDING,
        ),
    ])
    await db_session.commit()

    rows = await TaskAssignmentService.list_for_user_today_with_locks(
        db_session, demo_child.id, demo_family.id
    )

    locked = [r for r in rows if r["is_locked"]]
    assert len(locked) == 1
    assert locked[0]["is_bonus"] is True
```

- [ ] **Step 2: Run, confirm it fails**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py::test_list_marks_gigs_locked_when_mandatory_pending -v`
Expected: FAIL — method missing.

- [ ] **Step 3: Implement list enrichment**

Add to `TaskAssignmentService`:

```python
    @staticmethod
    async def list_for_user_today_with_locks(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
    ) -> list[dict]:
        """Return today's assignments for user with is_locked, approval_status, proof_text."""
        today = await TaskAssignmentService._user_local_today(db, user_id)
        all_done = await TaskAssignmentService.check_all_required_done_today(
            db, user_id, family_id, today
        )
        from sqlalchemy.orm import selectinload
        q = (
            select(TaskAssignment)
            .options(selectinload(TaskAssignment.template))
            .where(
                TaskAssignment.assigned_to == user_id,
                TaskAssignment.family_id == family_id,
                TaskAssignment.assigned_date == today,
            )
            .order_by(TaskAssignment.assigned_date)
        )
        rows = (await db.execute(q)).scalars().all()
        out = []
        for r in rows:
            is_bonus = r.template.is_bonus
            out.append({
                "id": r.id,
                "template_id": r.template_id,
                "title": r.template.title,
                "points": r.template.points,
                "is_bonus": is_bonus,
                "status": r.status.value,
                "approval_status": r.approval_status.value,
                "proof_text": r.proof_text,
                "is_locked": is_bonus and not all_done and r.status != AssignmentStatus.COMPLETED,
                "assigned_date": r.assigned_date,
                "completed_at": r.completed_at,
            })
        return out
```

- [ ] **Step 4: Confirm test passes**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py::test_list_marks_gigs_locked_when_mandatory_pending -v`
Expected: PASS

- [ ] **Step 5: Wire `/today` and `/week` routes to expose new fields**

In `backend/app/api/routes/task_assignments.py`, locate the `@router.get("/today")` handler (around line 101). After the existing query, attach the same `is_locked`/`approval_status`/`proof_text` fields to the response rows. For the existing serialization (search for the dict literal around line 220-250 — the inline mapping of fields), add:

```python
        "is_locked": getattr(assignment, "_is_locked", False),
        "approval_status": (
            assignment.approval_status.value
            if assignment.approval_status else "none"
        ),
        "proof_text": assignment.proof_text,
```

Then in the `/today` handler, before serialization, mark each assignment:

```python
    all_done = await TaskAssignmentService.check_all_required_done_today(
        db, current_user.id, current_user.family_id, date.today()
    )
    for a in assignments:
        a._is_locked = (
            a.template.is_bonus
            and not all_done
            and a.status != AssignmentStatus.COMPLETED
        )
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/app/api/routes/task_assignments.py backend/tests/test_gig_gating.py
git commit -m "feat(api): expose is_locked + approval_status on assignment list"
```

---

## Task 8: API routes — proof on complete, approval endpoints

**Files:**
- Modify: `backend/app/api/routes/task_assignments.py`

- [ ] **Step 1: Update `/complete` route to accept proof_text**

In `backend/app/api/routes/task_assignments.py` near line 178, change the route signature to accept body:

```python
from app.schemas.task_assignment import (
    ...existing imports...,
    CompleteAssignmentRequest,
    ApprovalDecision,
    GigApprovalRow,
)


@router.patch("/{assignment_id}/complete", response_model=TaskAssignmentWithDetails)
async def complete_assignment(
    assignment_id: UUID,
    payload: CompleteAssignmentRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an assignment as completed (proof_text required for gigs)."""
    assignment = await TaskAssignmentService.complete_assignment(
        db,
        assignment_id=assignment_id,
        family_id=current_user.family_id,
        user_id=current_user.id,
        proof_text=(payload.proof_text if payload else None),
    )
    return _to_response(assignment)
```

(If a `_to_response` helper isn't present, mirror the existing inline serialization.)

- [ ] **Step 2: Add `/pending-approvals` and `/{id}/approve` routes**

Append to the same file:

```python
@router.get("/pending-approvals", response_model=List[GigApprovalRow])
async def list_pending_approvals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != UserRole.PARENT:
        raise HTTPException(status_code=403, detail="Parents only")
    rows = await TaskAssignmentService.list_pending_approvals(db, current_user.family_id)
    return [
        GigApprovalRow(
            assignment_id=r.id,
            template_id=r.template_id,
            template_title=r.template.title,
            points=r.template.points,
            assigned_to=r.assigned_to,
            assigned_to_name=r.assignee.name if r.assignee else "",
            completed_at=r.completed_at,
            proof_text=r.proof_text,
        )
        for r in rows
    ]


@router.post("/{assignment_id}/approve", response_model=TaskAssignmentWithDetails)
async def approve_assignment(
    assignment_id: UUID,
    decision: ApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    assignment = await TaskAssignmentService.approve_gig(
        db,
        assignment_id=assignment_id,
        family_id=current_user.family_id,
        parent_id=current_user.id,
        approve=decision.approve,
        notes=decision.notes,
    )
    return _to_response(assignment)
```

Add `from app.models.user import UserRole` if not already imported.

- [ ] **Step 3: Smoke test routes via curl**

Run:
```bash
docker compose restart backend
sleep 3
curl -s http://localhost:8003/openapi.json | python3 -c "import sys,json; ops=json.load(sys.stdin)['paths']; print([p for p in ops if 'approv' in p or 'complete' in p])"
```
Expected: prints list including `/api/task-assignments/pending-approvals` and `/api/task-assignments/{assignment_id}/approve`.

- [ ] **Step 4: Run full backend tests**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py tests/test_gig_approval.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/task_assignments.py
git commit -m "feat(api): proof_text on complete, /pending-approvals, /approve routes"
```

---

## Task 9: Migration assertions test

**Files:**
- Create: `backend/tests/test_migration_mandatory_zero.py`

- [ ] **Step 1: Write the test**

```python
"""Assert migration outcomes are durable."""
import pytest
from sqlalchemy import select, func, text
from app.models.task_template import TaskTemplate


@pytest.mark.asyncio
async def test_all_mandatory_templates_have_zero_points(db_session):
    bad = await db_session.scalar(
        select(func.count()).select_from(TaskTemplate).where(
            TaskTemplate.is_bonus.is_(False),
            TaskTemplate.points != 0,
        )
    )
    assert bad == 0


@pytest.mark.asyncio
async def test_check_constraint_rejects_nonzero_mandatory_insert(db_session, demo_family):
    with pytest.raises(Exception, match="chk_mandatory_zero_points|check constraint"):
        await db_session.execute(text(
            "INSERT INTO task_templates "
            "(id, title, points, interval_days, assignment_type, is_bonus, is_active, family_id, created_at, updated_at) "
            "VALUES (gen_random_uuid(), 'bad', 5, 1, 'auto', false, true, :fid, NOW(), NOW())"
        ), {"fid": str(demo_family.id)})
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_default_gig_pack_seeded(db_session, demo_family):
    titles = ["Cook family dinner", "Plan next 3 days of meals", "Help with grocery shopping"]
    for t in titles:
        found = await db_session.scalar(
            select(func.count()).select_from(TaskTemplate).where(
                TaskTemplate.family_id == demo_family.id,
                TaskTemplate.title == t,
                TaskTemplate.is_bonus.is_(True),
            )
        )
        assert found >= 1, f"Default gig '{t}' missing"
```

- [ ] **Step 2: Run**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_migration_mandatory_zero.py -v`
Expected: 3 PASS (assumes migration already applied locally in Task 1).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_migration_mandatory_zero.py
git commit -m "test(migration): assert zero-mandatory, CHECK constraint, gig pack seed"
```

---

## Task 10: Seed gig pack on new family creation

**Files:**
- Modify: `backend/app/services/family_service.py`

- [ ] **Step 1: Add helper + call from create**

In `backend/app/services/family_service.py`, locate `class FamilyService:` and add:

```python
    DEFAULT_GIGS = [
        ("Learn a topic + writeup", "Pick something new (podman, git, a recipe). Read up, then write 5-10 sentences on what you learned.", 30),
        ("Read book chapter + discuss", "Read a chapter, then sit with a parent to discuss the main idea.", 20),
        ("Plan next 3 days of meals", "Propose breakfasts, lunches, and dinners for the next 3 days. List groceries needed.", 25),
        ("Help with grocery shopping", "Help compile the list, go to the store, and help carry/put away.", 15),
        ("Cook family dinner", "Plan, cook, and serve a family dinner with parent supervision.", 25),
        ("Tech-help parent (15 min)", "Help a parent with a phone/computer task for at least 15 minutes.", 10),
    ]

    @staticmethod
    async def _seed_default_gigs(db: AsyncSession, family_id):
        from app.models.task_template import TaskTemplate, AssignmentType
        for title, description, points in FamilyService.DEFAULT_GIGS:
            db.add(TaskTemplate(
                title=title,
                description=description,
                points=points,
                interval_days=7,
                assignment_type=AssignmentType.AUTO,
                is_bonus=True,
                is_active=True,
                family_id=family_id,
            ))
        await db.flush()
```

In the existing `create_family` (or equivalent creation method), after the family row is committed:

```python
        await FamilyService._seed_default_gigs(db, family.id)
        await db.commit()
```

- [ ] **Step 2: Add a test**

Append to `backend/tests/test_migration_mandatory_zero.py`:

```python
@pytest.mark.asyncio
async def test_new_family_gets_default_gigs(db_session):
    from app.services.family_service import FamilyService
    family = await FamilyService.create_family(db_session, name="Brand New Fam")
    count = await db_session.scalar(
        select(func.count()).select_from(TaskTemplate).where(
            TaskTemplate.family_id == family.id,
            TaskTemplate.is_bonus.is_(True),
        )
    )
    assert count == len(FamilyService.DEFAULT_GIGS)
```

- [ ] **Step 3: Run**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_migration_mandatory_zero.py::test_new_family_gets_default_gigs -v`
Expected: PASS

If the existing `create_family` signature differs, adjust call args accordingly. (Read the file before editing if uncertain.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/family_service.py backend/tests/test_migration_mandatory_zero.py
git commit -m "feat(family): seed default gig pack on new family creation"
```

---

## Task 11: Frontend — assignment list lock badge + gig completion modal

**Files:**
- Modify: `frontend/src/pages/parent/assignments.astro`
- Modify: `frontend/src/pages/api/assignments/complete.ts`

- [ ] **Step 1: Update complete.ts proxy to forward proof_text**

Edit `frontend/src/pages/api/assignments/complete.ts`. Locate the body construction and ensure the body forwarded to the backend includes `proof_text` from the inbound request body:

```ts
export const POST: APIRoute = async ({ request, cookies }) => {
  const body = await request.json().catch(() => ({}));
  const { assignment_id, proof_text } = body;
  const token = cookies.get("access_token")?.value;
  const res = await fetch(
    `${API_BASE}/api/task-assignments/${assignment_id}/complete`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ proof_text: proof_text ?? null }),
    }
  );
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json" },
  });
};
```

Match the existing import style (`API_BASE`) used in sibling files.

- [ ] **Step 2: Update assignments.astro**

In `frontend/src/pages/parent/assignments.astro`, find the row rendering loop. For each assignment add:

```astro
{assignment.is_locked && (
  <span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-amber-100 text-amber-800" title="Finish today's mandatory tasks to unlock">
    🔒 Locked
  </span>
)}
{assignment.approval_status === "pending" && (
  <span class="px-2 py-0.5 text-xs rounded bg-amber-100 text-amber-800">Awaiting approval</span>
)}
{assignment.approval_status === "approved" && (
  <span class="px-2 py-0.5 text-xs rounded bg-green-100 text-green-800">Approved</span>
)}
{assignment.approval_status === "rejected" && (
  <span class="px-2 py-0.5 text-xs rounded bg-red-100 text-red-800">Rejected</span>
)}
```

Disable the "Complete" button when `assignment.is_locked` is true.

For the gig completion flow, add a client-side modal (vanilla JS in `<script>` block) that opens when clicking complete on a row where `is_bonus=true`. The modal must collect a `proof_text` value and POST to `/api/assignments/complete` with `{ assignment_id, proof_text }`. For mandatory rows (`is_bonus=false`), submit immediately with `proof_text: null`.

Modal markup (hidden by default):

```html
<dialog id="gig-proof-modal" class="rounded-lg p-6 backdrop:bg-black/40 max-w-md">
  <h3 class="text-lg font-semibold mb-3">Tell us what you did</h3>
  <p class="text-sm text-gray-600 mb-3">A parent will review this and approve the points.</p>
  <textarea id="gig-proof-text" rows="5" class="w-full border rounded p-2 mb-3" placeholder="What did you learn / make / accomplish?"></textarea>
  <div class="flex justify-end gap-2">
    <button id="gig-proof-cancel" class="px-3 py-1.5 rounded border">Cancel</button>
    <button id="gig-proof-submit" class="px-3 py-1.5 rounded bg-emerald-600 text-white">Submit for approval</button>
  </div>
</dialog>
```

`<script>` (Astro-side):

```html
<script>
  const modal = document.getElementById("gig-proof-modal") as HTMLDialogElement;
  const textarea = document.getElementById("gig-proof-text") as HTMLTextAreaElement;
  let pendingAssignmentId: string | null = null;

  document.querySelectorAll<HTMLButtonElement>("[data-complete-btn]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.assignmentId!;
      const isGig = btn.dataset.isBonus === "true";
      if (isGig) {
        pendingAssignmentId = id;
        textarea.value = "";
        modal.showModal();
      } else {
        await submitComplete(id, null);
      }
    });
  });

  document.getElementById("gig-proof-cancel")!.addEventListener("click", () => modal.close());
  document.getElementById("gig-proof-submit")!.addEventListener("click", async () => {
    if (!textarea.value.trim()) { alert("Tell us what you did"); return; }
    await submitComplete(pendingAssignmentId!, textarea.value.trim());
    modal.close();
  });

  async function submitComplete(assignment_id: string, proof_text: string | null) {
    const r = await fetch("/api/assignments/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assignment_id, proof_text }),
    });
    if (r.ok) location.reload();
    else alert(`Error: ${await r.text()}`);
  }
</script>
```

For each complete button add `data-assignment-id={assignment.id}` and `data-is-bonus={String(assignment.is_bonus)}` and `data-complete-btn`.

- [ ] **Step 3: Manual smoke test in browser**

Run: `docker compose up -d frontend backend` (already up — `docker compose restart frontend`)

In a browser logged in as `lucas@demo.com` (TEEN with seeded mandatory + gig):
1. Navigate to `/parent/assignments` (or the child-side equivalent).
2. With mandatory pending, the gig row shows "🔒 Locked" and Complete button is disabled.
3. Complete all mandatory rows — lock badge disappears.
4. Click Complete on a gig — modal appears. Submit with text. Row gets "Awaiting approval" badge.

Document any layout issues in the next task (parent approval page).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/parent/assignments.astro frontend/src/pages/api/assignments/complete.ts
git commit -m "feat(frontend): lock badge + gig proof modal on assignments list"
```

---

## Task 12: Frontend — parent approvals page + nav badge

**Files:**
- Create: `frontend/src/pages/parent/approvals.astro`
- Create: `frontend/src/pages/api/assignments/pending-approvals.ts`
- Create: `frontend/src/pages/api/assignments/approve.ts`
- Modify: nav header partial (search for the parent nav component)

- [ ] **Step 1: Create `pending-approvals.ts` proxy**

`frontend/src/pages/api/assignments/pending-approvals.ts`:

```ts
import type { APIRoute } from "astro";

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || "http://backend:8000";

export const GET: APIRoute = async ({ cookies }) => {
  const token = cookies.get("access_token")?.value;
  const r = await fetch(`${API_BASE}/api/task-assignments/pending-approvals`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return new Response(await r.text(), {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
};
```

- [ ] **Step 2: Create `approve.ts` proxy**

`frontend/src/pages/api/assignments/approve.ts`:

```ts
import type { APIRoute } from "astro";

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || "http://backend:8000";

export const POST: APIRoute = async ({ request, cookies }) => {
  const body = await request.json();
  const { assignment_id, approve, notes } = body;
  const token = cookies.get("access_token")?.value;
  const r = await fetch(
    `${API_BASE}/api/task-assignments/${assignment_id}/approve`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ approve, notes }),
    }
  );
  return new Response(await r.text(), {
    status: r.status,
    headers: { "Content-Type": "application/json" },
  });
};
```

- [ ] **Step 3: Create `approvals.astro`**

`frontend/src/pages/parent/approvals.astro`:

```astro
---
import Layout from "../../layouts/Layout.astro";
import { getSessionUser } from "../../lib/session";

const user = await getSessionUser(Astro);
if (!user || user.role !== "parent") {
  return Astro.redirect("/login");
}

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL || "http://backend:8000";
const token = Astro.cookies.get("access_token")?.value;
const r = await fetch(`${API_BASE}/api/task-assignments/pending-approvals`, {
  headers: { Authorization: `Bearer ${token}` },
});
const rows = r.ok ? await r.json() : [];
---

<Layout title="Gig approvals">
  <main class="max-w-3xl mx-auto p-6">
    <h1 class="text-2xl font-semibold mb-4">Pending gig approvals</h1>
    {rows.length === 0 ? (
      <p class="text-gray-500">No gigs waiting for approval.</p>
    ) : (
      <ul class="space-y-4">
        {rows.map((row) => (
          <li class="border rounded-lg p-4 bg-white" data-id={row.assignment_id}>
            <div class="flex justify-between items-start mb-2">
              <div>
                <h3 class="font-medium">{row.template_title}</h3>
                <p class="text-sm text-gray-600">
                  {row.assigned_to_name} · {row.points} pts
                </p>
              </div>
              <span class="text-xs text-gray-500">
                {new Date(row.completed_at).toLocaleString()}
              </span>
            </div>
            <p class="text-sm bg-gray-50 rounded p-3 mb-3 whitespace-pre-wrap">
              {row.proof_text || "(no proof text)"}
            </p>
            <textarea
              data-notes
              rows="2"
              class="w-full border rounded p-2 mb-2 text-sm"
              placeholder="Notes (optional)"
            ></textarea>
            <div class="flex justify-end gap-2">
              <button
                data-action="reject"
                class="px-3 py-1.5 rounded border text-red-700"
              >Reject</button>
              <button
                data-action="approve"
                class="px-3 py-1.5 rounded bg-emerald-600 text-white"
              >Approve</button>
            </div>
          </li>
        ))}
      </ul>
    )}
  </main>
</Layout>

<script>
  document.querySelectorAll<HTMLLIElement>("li[data-id]").forEach((li) => {
    const id = li.dataset.id!;
    const notes = li.querySelector<HTMLTextAreaElement>("[data-notes]")!;
    li.querySelectorAll<HTMLButtonElement>("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const approve = btn.dataset.action === "approve";
        const r = await fetch("/api/assignments/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assignment_id: id,
            approve,
            notes: notes.value.trim() || null,
          }),
        });
        if (r.ok) li.remove();
        else alert(`Error: ${await r.text()}`);
      });
    });
  });
</script>
```

- [ ] **Step 4: Add nav badge**

Locate the parent nav header (search): `grep -rln "parent/assignments\|parent/tasks" frontend/src/layouts frontend/src/components`.

In the parent nav, fetch the pending count once per page render and show a small dot/number next to the "Approvals" link. Add a link to `/parent/approvals` with a dot if `count > 0`.

Astro frontmatter:
```astro
const apprResp = await fetch(`${API_BASE}/api/task-assignments/pending-approvals`, {
  headers: { Authorization: `Bearer ${token}` },
});
const pendingCount = apprResp.ok ? (await apprResp.json()).length : 0;
```

Render:
```astro
<a href="/parent/approvals" class="relative px-3 py-2">
  Approvals
  {pendingCount > 0 && (
    <span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">{pendingCount}</span>
  )}
</a>
```

- [ ] **Step 5: Manual smoke test**

In browser:
1. As `mom@demo.com` (parent), navigate to `/parent/approvals`.
2. Approve a pending gig — row disappears. Child's points balance increases by template points.
3. Reject another — row disappears, no points credited.
4. Nav badge count decrements correctly.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/parent/approvals.astro frontend/src/pages/api/assignments/approve.ts frontend/src/pages/api/assignments/pending-approvals.ts frontend/src/layouts frontend/src/components
git commit -m "feat(frontend): parent approvals page + nav badge"
```

---

## Task 13: E2E Playwright test

**Files:**
- Create: `e2e-tests/tests/gigs.spec.ts`

- [ ] **Step 1: Write the test**

```ts
import { test, expect } from "@playwright/test";

test.describe("Gigs lifecycle", () => {
  test("child cannot complete gig while mandatory pending, parent approves after unlock", async ({ page, context }) => {
    // Sign in as child
    await page.goto("/login");
    await page.fill('input[name="email"]', "lucas@demo.com");
    await page.fill('input[name="password"]', "password123");
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/(parent|dashboard|child)/);

    await page.goto("/parent/assignments");

    // Expect a lock badge somewhere
    await expect(page.locator("text=Locked").first()).toBeVisible();

    // Complete all mandatory
    const mandatoryButtons = page.locator('[data-complete-btn][data-is-bonus="false"]');
    const n = await mandatoryButtons.count();
    for (let i = 0; i < n; i++) {
      await mandatoryButtons.nth(0).click(); // collection shrinks after reload
      await page.waitForLoadState("networkidle");
    }

    // Click a gig complete button (modal should open)
    await page.locator('[data-complete-btn][data-is-bonus="true"]').first().click();
    await page.locator("#gig-proof-text").fill("read chapter on rootless podman");
    await page.locator("#gig-proof-submit").click();
    await page.waitForLoadState("networkidle");
    await expect(page.locator("text=Awaiting approval").first()).toBeVisible();

    // Sign out, sign in as parent
    await context.clearCookies();
    await page.goto("/login");
    await page.fill('input[name="email"]', "mom@demo.com");
    await page.fill('input[name="password"]', "password123");
    await page.click('button[type="submit"]');
    await page.waitForURL(/\/parent/);

    await page.goto("/parent/approvals");
    await expect(page.locator("text=read chapter on rootless podman")).toBeVisible();
    await page.locator('button[data-action="approve"]').first().click();
    await page.waitForLoadState("networkidle");

    // Approval list shrinks
    await expect(page.locator("text=read chapter on rootless podman")).not.toBeVisible();
  });
});
```

- [ ] **Step 2: Run**

Run: `cd e2e-tests && npm run test -- gigs.spec.ts`
Expected: 1 PASS

- [ ] **Step 3: Commit**

```bash
git add e2e-tests/tests/gigs.spec.ts
git commit -m "test(e2e): gigs lifecycle — lock, proof modal, parent approval"
```

---

## Final verification

- [ ] **Step 1: Run full backend test suite**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v`
Expected: all new tests PASS. Pre-existing failures (per CLAUDE.md: 51 stub failures) remain unchanged in count.

- [ ] **Step 2: Manual end-to-end smoke in browser**

1. Sign in as child → confirm gigs locked while mandatory pending.
2. Complete mandatory → lock clears (no points credited for mandatory).
3. Complete gig with proof → row goes "Awaiting approval".
4. Sign in as parent → see pending in `/parent/approvals` and nav badge.
5. Approve → child balance increases by template.points, badge clears.

- [ ] **Step 3: Push branch + open PR**

```bash
git push -u origin HEAD
gh pr create --title "Mandatory tasks zero points, gigs gated + parent-approved" --body "$(cat <<'EOF'
## Summary
- Mandatory tasks (is_bonus=false) award no points and create no point_transaction row
- Gigs (is_bonus=true) require all of today's mandatory done first, require proof text, and enter PENDING approval
- Parent approval credits gig points via new GIG_APPROVED transaction type
- Default gig pack seeded per existing family and on new family creation
- families.timezone column added for accurate "today" gating

Spec: docs/superpowers/specs/2026-05-22-mandatory-vs-gigs-design.md

## Test plan
- [ ] backend pytest tests/test_gig_gating.py tests/test_gig_approval.py tests/test_migration_mandatory_zero.py
- [ ] e2e: npm run test -- gigs.spec.ts
- [ ] manual: child locks → complete mandatory → unlock → submit gig with proof → parent approves → balance updates

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
