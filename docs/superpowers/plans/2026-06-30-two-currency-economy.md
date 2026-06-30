# Two-Currency Economy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate privilege **points** (earned by mandatory chores, spent on rewards) from **cash** (earned by gigs, paid out by parents) — two independent balances.

**Architecture:** Add `User.cash_cents` + a `cash_transactions` ledger (mirror of `point_transactions`). Mandatory-chore completion credits `effective_points` to `user.points`; gig approval credits cash (`pts*100` cents) instead of points. Parents record payouts that debit cash. Remove the dead `points-conversion` route and the `chk_mandatory_zero_points` constraint/validator (the prod task-creation 422).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async), Alembic, Pytest; Astro 5 frontend.

## Global Constraints

- Multi-tenant: every new model has non-nullable `family_id` FK; every query filters by the JWT's `family_id`.
- Money is stored as integer **centavos**. Gig points→cents = `× 100`. Display `$X.XX MXN`.
- Aggregated numeric values cast to `int()` before assigning to Pydantic fields (asyncpg Decimal → JSON-string bug; see CLAUDE.md).
- Tests build schema from `Base.metadata.create_all` (conftest line 94), NOT migrations. Model + `__table_args__` changes are seen by tests immediately; the Alembic migration is for prod only.
- Migration head to branch from: **`mcp_restricted_role`** (`backend/migrations/versions/2026_06_24_mcp_restricted_role.py`).
- Run backend tests in the container: `podman exec -e PYTHONPATH=/app family_app_backend pytest <path> -v`. If no local container, run inside the prod backend container (read-only test DB on port 5435 is local-only — for prod-container runs use the suite the same way CLAUDE.md documents). Prefer local podman.
- `user.points` keeps its meaning = privilege points. No backfill of historical balances.

---

## File Structure

**Create**
- `backend/app/models/cash_transaction.py` — `CashTransaction` model + `CashTransactionType`.
- `backend/app/services/cash_service.py` — `CashService`.
- `backend/app/schemas/cash.py` — cash request/response schemas.
- `backend/app/api/routes/cash.py` — `/api/cash/*` routes.
- `backend/migrations/versions/2026_06_30_two_currency_economy.py` — Alembic migration.
- `backend/tests/test_cash_service.py`
- `backend/tests/test_two_currency_economy.py`
- `backend/tests/test_openai_bridge_gemini_safe.py`
- `frontend/src/pages/parent/payouts.astro` — parent payout screen.

**Modify**
- `backend/app/models/user.py` — add `cash_cents` column + `cash_transactions` relationship.
- `backend/app/models/__init__.py` — register `CashTransaction`, `CashTransactionType`.
- `backend/app/models/task_template.py` — remove `chk_mandatory_zero_points` CheckConstraint.
- `backend/app/schemas/task_template.py` — remove both `_enforce_mandatory_zero_points` validators.
- `backend/app/services/points_service.py` — add `award_assignment_completion` (no-commit).
- `backend/app/services/task_assignment_service.py` — mandatory path awards points; `_award_assignment` + `_settle_collaboration` award cash.
- `backend/app/main.py` — register cash router; remove `points_conversion` import + include.
- Frontend: kid dashboard, gig board, task cards, parent nav; remove `PointsConverter` usage.

**Delete**
- `backend/app/api/routes/points_conversion.py`
- `frontend/src/components/PointsConverter.astro`
- `frontend/src/pages/api/points/convert.ts`

---

## Task 1: CashTransaction model + User.cash_cents

**Files:**
- Create: `backend/app/models/cash_transaction.py`
- Modify: `backend/app/models/user.py:28` (add column), `:83` (add relationship)
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_cash_service.py`

**Interfaces:**
- Produces: `CashTransaction` (cols: `id, user_id, family_id, type, amount_cents, balance_before, balance_after, assignment_id?, gig_claim_id?, created_by?, description, created_at`); `CashTransactionType` enum `{GIG_EARNED, PAYOUT, ADJUSTMENT}`; `User.cash_cents: int`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cash_service.py
import pytest
from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_user_has_cash_cents_default_zero(db, family):
    u = User(email="kid-cash@test.com", name="Kid", role=UserRole.CHILD,
             family_id=family.id, email_verified=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    assert u.cash_cents == 0


@pytest.mark.asyncio
async def test_cash_transaction_row_persists(db, family):
    u = User(email="kid-cash2@test.com", name="Kid", role=UserRole.CHILD,
             family_id=family.id, email_verified=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    tx = CashTransaction(
        user_id=u.id, family_id=family.id,
        type=CashTransactionType.GIG_EARNED,
        amount_cents=5000, balance_before=0, balance_after=5000,
        description="test",
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    assert tx.id is not None
    assert tx.amount_cents == 5000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_cash_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models.cash_transaction` / `cash_cents` unknown.

- [ ] **Step 3: Create the model**

```python
# backend/app/models/cash_transaction.py
"""CashTransaction model — ledger for the cash currency (gigs → payouts).

Mirror of PointTransaction, but cash lives in centavos. Points (privileges)
and cash (money) are intentionally separate currencies; see
docs/superpowers/specs/2026-06-30-two-currency-economy-design.md.
"""
from sqlalchemy import Column, Integer, DateTime, ForeignKey, Enum as SQLEnum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

from app.core.database import Base


class CashTransactionType(str, enum.Enum):
    GIG_EARNED = "gig_earned"      # cash credited when a gig is approved
    PAYOUT = "payout"             # parent paid the kid (debit)
    ADJUSTMENT = "adjustment"     # manual parent adjustment (signed)


class CashTransaction(Base):
    """Cash ledger row (centavos). Positive = credit, negative = debit."""

    __tablename__ = "cash_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    type = Column(SQLEnum(CashTransactionType), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"),
                       nullable=False, index=True)

    balance_before = Column(Integer, nullable=False, default=0)
    balance_after = Column(Integer, nullable=False)

    # Links — both nullable; gig settlement keys off assignment_id (mirrors
    # PointTransaction). gig_claim_id kept for parity with the gig-claim flow.
    assignment_id = Column(UUID(as_uuid=True),
                           ForeignKey("task_assignments.id", ondelete="SET NULL"),
                           nullable=True)
    gig_claim_id = Column(UUID(as_uuid=True),
                          ForeignKey("gig_claims.id", ondelete="SET NULL"),
                          nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
                        nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow,
                        nullable=False, index=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="cash_transactions")
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self):
        return f"<CashTransaction(id={self.id}, type={self.type.value}, amount_cents={self.amount_cents})>"
```

- [ ] **Step 4: Add `cash_cents` column + relationship to User**

In `backend/app/models/user.py`, after line 28 (`points = Column(...)`):

```python
    cash_cents = Column(Integer, default=0, nullable=False, server_default="0")
```

After line 83 (`point_transactions = relationship(...)`):

```python
    cash_transactions = relationship(
        "CashTransaction",
        foreign_keys="CashTransaction.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
```

- [ ] **Step 5: Register in models/__init__.py**

After the `from app.models.point_transaction import ...` line:

```python
from app.models.cash_transaction import CashTransaction, CashTransactionType
```

Add `"CashTransaction"` and `"CashTransactionType"` to `__all__`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_cash_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/cash_transaction.py backend/app/models/user.py backend/app/models/__init__.py backend/tests/test_cash_service.py
git commit -m "feat(economy): CashTransaction model + User.cash_cents balance"
```

---

## Task 2: Allow points on mandatory tasks (drop constraint + validators)

**Files:**
- Modify: `backend/app/models/task_template.py:59-64` (remove CheckConstraint)
- Modify: `backend/app/schemas/task_template.py:70-77, 103-111` (remove validators)
- Test: `backend/tests/test_two_currency_economy.py`

**Interfaces:**
- Produces: `TaskTemplateCreate(is_bonus=False, points=10)` validates; DB accepts a mandatory template with `points>0`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_two_currency_economy.py
import pytest
from app.schemas.task_template import TaskTemplateCreate
from app.models.task_template import TaskTemplate


def test_mandatory_task_can_have_points_schema():
    # Previously raised: "Mandatory tasks must have points=0"
    t = TaskTemplateCreate(title="Sweep", is_bonus=False, points=10,
                           assignment_type="auto", gig_mode="claim")
    assert t.points == 10
    assert t.is_bonus is False


@pytest.mark.asyncio
async def test_mandatory_template_with_points_persists(db, family):
    t = TaskTemplate(title="Sweep", points=10, interval_days=1,
                     is_bonus=False, is_active=True, family_id=family.id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    assert t.points == 10  # no chk_mandatory_zero_points violation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py -v`
Expected: FAIL — schema `ValueError` and/or `IntegrityError chk_mandatory_zero_points`.

- [ ] **Step 3: Remove the CheckConstraint**

In `backend/app/models/task_template.py`, delete from `__table_args__`:

```python
        CheckConstraint(
            "is_bonus = true OR points = 0",
            name="chk_mandatory_zero_points",
        ),
```

Leave the `chk_effort_level_range` constraint. `__table_args__` becomes a single-constraint tuple.

- [ ] **Step 4: Remove the Pydantic validators**

In `backend/app/schemas/task_template.py`, delete the `_enforce_mandatory_zero_points` method from `TaskTemplateCreate` (lines ~70-77) and from `TaskTemplateUpdate` (lines ~103-111). Remove the now-unused `model_validator` import if nothing else uses it (check first — keep if used elsewhere).

- [ ] **Step 5: Run tests to verify they pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/task_template.py backend/app/schemas/task_template.py backend/tests/test_two_currency_economy.py
git commit -m "fix(tasks): allow points on mandatory tasks (drop zero-points constraint+validator) — fixes create-task 422"
```

---

## Task 3: CashService

**Files:**
- Create: `backend/app/services/cash_service.py`
- Test: `backend/tests/test_cash_service.py` (extend)

**Interfaces:**
- Consumes: `CashTransaction`, `CashTransactionType`, `User` (Task 1).
- Produces:
  - `CashService.get_balance(db, user_id) -> int`
  - `CashService.award_gig_cash(db, user_id, family_id, assignment_id, amount_cents, description=None) -> CashTransaction` (NO commit; mirrors `award_gig_points`)
  - `CashService.record_payout(db, user_id, family_id, amount_cents, created_by) -> CashTransaction` (commits)
  - `CashService.adjust(db, user_id, family_id, amount_cents, reason, created_by) -> CashTransaction` (commits)
  - `CashService.get_history(db, user_id, limit=50) -> list[CashTransaction]`
  - `CashService.get_summary(db, user_id) -> dict` keys: `current_balance, total_earned, total_paid`

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_cash_service.py
import pytest
from uuid import uuid4
from app.models.user import User, UserRole
from app.services.cash_service import CashService
from app.core.exceptions import ValidationException


async def _kid(db, family, cents=0):
    u = User(email=f"k{uuid4().hex[:8]}@t.com", name="K", role=UserRole.CHILD,
             family_id=family.id, email_verified=True, cash_cents=cents)
    db.add(u); await db.commit(); await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_award_gig_cash_credits_balance(db, family):
    u = await _kid(db, family)
    await CashService.award_gig_cash(db, u.id, family.id, None, 5000, "gig")
    await db.commit(); await db.refresh(u)
    assert u.cash_cents == 5000
    assert await CashService.get_balance(db, u.id) == 5000


@pytest.mark.asyncio
async def test_award_gig_cash_supports_negative_clawback(db, family):
    u = await _kid(db, family, cents=5000)
    await CashService.award_gig_cash(db, u.id, family.id, None, -2000, "resplit")
    await db.commit(); await db.refresh(u)
    assert u.cash_cents == 3000


@pytest.mark.asyncio
async def test_record_payout_partial(db, family):
    u = await _kid(db, family, cents=12000)
    parent = await _kid(db, family)  # any user id for created_by
    tx = await CashService.record_payout(db, u.id, family.id, 5000, parent.id)
    await db.refresh(u)
    assert u.cash_cents == 7000
    assert tx.amount_cents == -5000


@pytest.mark.asyncio
async def test_record_payout_rejects_overdraw(db, family):
    u = await _kid(db, family, cents=3000)
    parent = await _kid(db, family)
    with pytest.raises(ValidationException):
        await CashService.record_payout(db, u.id, family.id, 9999, parent.id)


@pytest.mark.asyncio
async def test_summary_math(db, family):
    u = await _kid(db, family)
    parent = await _kid(db, family)
    await CashService.award_gig_cash(db, u.id, family.id, None, 10000, "g")
    await db.commit()
    await CashService.record_payout(db, u.id, family.id, 4000, parent.id)
    s = await CashService.get_summary(db, u.id)
    assert s["current_balance"] == 6000
    assert s["total_earned"] == 10000
    assert s["total_paid"] == 4000
```

- [ ] **Step 2: Run to verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_cash_service.py -v`
Expected: FAIL — `app.services.cash_service` missing.

- [ ] **Step 3: Implement CashService**

```python
# backend/app/services/cash_service.py
"""CashService — cash currency ledger (centavos). Gigs credit; parents pay out.

Symmetric with PointsService but a separate balance (User.cash_cents) and
ledger (cash_transactions). Cash never converts to/from points.
"""
from uuid import UUID
from typing import Optional, List

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.core.exceptions import ValidationException
from app.services.base_service import get_user_by_id


class CashService:
    @staticmethod
    async def get_balance(db: AsyncSession, user_id: UUID) -> int:
        user = await get_user_by_id(db, user_id)
        return user.cash_cents

    @staticmethod
    async def award_gig_cash(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        assignment_id: Optional[UUID],
        amount_cents: int,
        description: Optional[str] = None,
    ) -> CashTransaction:
        """Credit (or claw back, if negative) gig cash. Caller commits."""
        user = await get_user_by_id(db, user_id)
        before = user.cash_cents
        tx = CashTransaction(
            type=CashTransactionType.GIG_EARNED,
            user_id=user_id,
            family_id=family_id,
            assignment_id=assignment_id,
            amount_cents=amount_cents,
            balance_before=before,
            balance_after=before + amount_cents,
            description=description or f"Gig — ${amount_cents/100:.2f} MXN",
        )
        user.cash_cents = before + amount_cents
        db.add(tx)
        return tx

    @staticmethod
    async def record_payout(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        created_by: UUID,
    ) -> CashTransaction:
        if amount_cents <= 0:
            raise ValidationException("Payout amount must be positive")
        user = await get_user_by_id(db, user_id)
        if amount_cents > user.cash_cents:
            raise ValidationException(
                f"Payout exceeds balance. Balance ${user.cash_cents/100:.2f}, "
                f"requested ${amount_cents/100:.2f}"
            )
        before = user.cash_cents
        tx = CashTransaction(
            type=CashTransactionType.PAYOUT,
            user_id=user_id,
            family_id=family_id,
            amount_cents=-amount_cents,
            balance_before=before,
            balance_after=before - amount_cents,
            created_by=created_by,
            description=f"Paid ${amount_cents/100:.2f} MXN",
        )
        user.cash_cents = before - amount_cents
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def adjust(
        db: AsyncSession,
        user_id: UUID,
        family_id: UUID,
        amount_cents: int,
        reason: str,
        created_by: UUID,
    ) -> CashTransaction:
        user = await get_user_by_id(db, user_id)
        before = user.cash_cents
        after = before + amount_cents
        if after < 0:
            after = 0
            amount_cents = -before
        tx = CashTransaction(
            type=CashTransactionType.ADJUSTMENT,
            user_id=user_id,
            family_id=family_id,
            amount_cents=amount_cents,
            balance_before=before,
            balance_after=after,
            created_by=created_by,
            description=reason,
        )
        user.cash_cents = after
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def get_history(db: AsyncSession, user_id: UUID, limit: int = 50) -> List[CashTransaction]:
        q = (select(CashTransaction)
             .where(CashTransaction.user_id == user_id)
             .order_by(CashTransaction.created_at.desc())
             .limit(limit))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def get_summary(db: AsyncSession, user_id: UUID) -> dict:
        user = await get_user_by_id(db, user_id)
        earned = (await db.execute(
            select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                and_(CashTransaction.user_id == user_id,
                     CashTransaction.amount_cents > 0)))).scalar() or 0
        paid = (await db.execute(
            select(func.coalesce(func.sum(CashTransaction.amount_cents), 0)).where(
                and_(CashTransaction.user_id == user_id,
                     CashTransaction.type == CashTransactionType.PAYOUT)))).scalar() or 0
        return {
            "current_balance": int(user.cash_cents),
            "total_earned": int(earned),
            "total_paid": int(abs(paid)),
        }
```

- [ ] **Step 4: Run to verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_cash_service.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cash_service.py backend/tests/test_cash_service.py
git commit -m "feat(economy): CashService (award/payout/adjust/summary)"
```

---

## Task 4: PointsService.award_assignment_completion (no-commit)

**Files:**
- Modify: `backend/app/services/points_service.py`
- Test: `backend/tests/test_two_currency_economy.py` (extend)

**Interfaces:**
- Consumes: `PointTransaction.create_assignment_completion` (exists), `get_user_by_id`.
- Produces: `PointsService.award_assignment_completion(db, user_id, assignment_id, points) -> PointTransaction` (NO commit; mutates `user.points`).

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_two_currency_economy.py
from app.services.points_service import PointsService


@pytest.mark.asyncio
async def test_award_assignment_completion_no_commit_credits_points(db, family):
    from app.models.user import User, UserRole
    u = User(email="kidp@test.com", name="Kid", role=UserRole.CHILD,
             family_id=family.id, email_verified=True, points=5)
    db.add(u); await db.commit(); await db.refresh(u)
    tx = await PointsService.award_assignment_completion(db, u.id, None, 10)
    await db.commit(); await db.refresh(u)
    assert u.points == 15
    assert tx.points == 10
```

- [ ] **Step 2: Run to verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py::test_award_assignment_completion_no_commit_credits_points -v`
Expected: FAIL — method missing.

- [ ] **Step 3: Implement (add to PointsService)**

```python
    @staticmethod
    async def award_assignment_completion(
        db: AsyncSession,
        user_id: UUID,
        assignment_id,
        points: int,
    ) -> "PointTransaction":
        """Credit points for a mandatory-chore completion. Caller commits.

        Mirrors award_gig_points (no commit) so it composes inside
        complete_assignment's single transaction.
        """
        user = await get_user_by_id(db, user_id)
        tx = PointTransaction.create_assignment_completion(
            user_id=user_id,
            assignment_id=assignment_id,
            points=points,
            balance_before=user.points,
        )
        user.points += points
        db.add(tx)
        return tx
```

- [ ] **Step 4: Run to verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/points_service.py backend/tests/test_two_currency_economy.py
git commit -m "feat(economy): PointsService.award_assignment_completion (no-commit chore award)"
```

---

## Task 5: Mandatory completion awards points

**Files:**
- Modify: `backend/app/services/task_assignment_service.py:714-720` (mandatory path)
- Test: `backend/tests/test_two_currency_economy.py` (extend)

**Interfaces:**
- Consumes: `PointsService.award_assignment_completion` (Task 4), `template.effective_points`.

- [ ] **Step 1: Write the failing test** (uses existing assignment fixtures/factories)

```python
# append to backend/tests/test_two_currency_economy.py
from datetime import date
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.services.task_assignment_service import TaskAssignmentService


@pytest.mark.asyncio
async def test_mandatory_completion_awards_effective_points(db, family, mandatory_template_factory):
    from app.models.user import User, UserRole
    kid = User(email="kidm@test.com", name="Kid", role=UserRole.CHILD,
               family_id=family.id, email_verified=True, points=0)
    db.add(kid); await db.commit(); await db.refresh(kid)
    tmpl = await mandatory_template_factory(family=family, points=10)  # effort 1 → effective 10
    a = TaskAssignment(template_id=tmpl.id, family_id=family.id,
                       assigned_to=kid.id, assigned_date=date.today(),
                       status=AssignmentStatus.PENDING)
    db.add(a); await db.commit(); await db.refresh(a)

    await TaskAssignmentService.complete_assignment(db, a.id, family.id, kid.id)
    await db.refresh(kid)
    assert kid.points == 10        # privilege points credited
    assert kid.cash_cents == 0     # mandatory never touches cash
```

(If `complete_assignment`'s signature differs, match the existing call sites — check `task_assignments` route. Adapt arg names, keep the assertions.)

- [ ] **Step 2: Run to verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py::test_mandatory_completion_awards_effective_points -v`
Expected: FAIL — `kid.points == 0` (mandatory currently awards nothing).

- [ ] **Step 3: Implement** — in the mandatory branch (`else:` at line 714):

```python
        else:
            # Mandatory path — silent completion, awards privilege points.
            assignment.status = AssignmentStatus.COMPLETED
            assignment.completed_at = datetime.now(timezone.utc)
            from app.services.points_service import PointsService
            await PointsService.award_assignment_completion(
                db, user_id, assignment.id, template.effective_points
            )
            from app.services.pet_service import PetService
            await PetService.on_task_completed(db, user_id, is_bonus=False)
```

- [ ] **Step 4: Run to verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/test_two_currency_economy.py
git commit -m "feat(economy): mandatory chore completion awards effective_points"
```

---

## Task 6: Gig approval awards cash (not points)

**Files:**
- Modify: `backend/app/services/task_assignment_service.py:801-816` (`_award_assignment`), `:819-901` (`_settle_collaboration`)
- Test: `backend/tests/test_two_currency_economy.py` (extend)

**Interfaces:**
- Consumes: `CashService.award_gig_cash` (Task 3), `template.award_points_per_completer`, `TaskTemplate.distribute_points`.
- Behavior: non-collaboration gig credits `award_points_per_completer * 100` cents; collaboration re-split computes net per completer from `CashTransaction` (GIG_EARNED) and credits the cash delta.

- [ ] **Step 1: Write the failing test** (auto-approve via trust streak so points/cash credit immediately)

```python
# append to backend/tests/test_two_currency_economy.py
@pytest.mark.asyncio
async def test_gig_approval_credits_cash_not_points(db, family, gig_template_factory):
    from app.models.user import User, UserRole
    from app.core.config import settings
    kid = User(email="kidg@test.com", name="Kid", role=UserRole.CHILD,
               family_id=family.id, email_verified=True, points=0, cash_cents=0,
               gig_trust_streak=max(1, settings.GIG_AUTO_APPROVE_STREAK))
    db.add(kid); await db.commit(); await db.refresh(kid)
    tmpl = await gig_template_factory(family=family, points=20)  # effort 1 → $20 → 2000 cents
    a = TaskAssignment(template_id=tmpl.id, family_id=family.id,
                       assigned_to=kid.id, assigned_date=date.today(),
                       status=AssignmentStatus.PENDING)
    db.add(a); await db.commit(); await db.refresh(a)

    await TaskAssignmentService.complete_assignment(
        db, a.id, family.id, kid.id, proof_text="did it")
    await db.refresh(kid)
    assert kid.cash_cents == 2000   # gig pays cash
    assert kid.points == 0          # gig does NOT touch points
```

- [ ] **Step 2: Run to verify fail**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py::test_gig_approval_credits_cash_not_points -v`
Expected: FAIL — `kid.points == 2000`, `kid.cash_cents == 0` (still points).

- [ ] **Step 3: Implement — `_award_assignment`**

```python
    @staticmethod
    async def _award_assignment(db: AsyncSession, assignment, template, user_id) -> int:
        """Credit a gig completer in CASH and return the cents credited.

        Non-collaboration gigs award the full effective value (× 100 cents).
        Collaboration re-splits the pot among approved completers.
        """
        from app.services.cash_service import CashService

        if (template.gig_mode or "claim") != "collaboration":
            cents = template.award_points_per_completer * 100
            await CashService.award_gig_cash(
                db, user_id, assignment.family_id, assignment.id, cents
            )
            return cents
        return await TaskAssignmentService._settle_collaboration(db, assignment, template)
```

(Return value is now **cents**. Update the two callers' notification text — auto-approve at ~696 and approve_gig at ~1073 — to display `${pts/100:.2f}` MXN instead of "pts". Search those sites and adjust the `pts` usages in the notification/push bodies.)

- [ ] **Step 4: Implement — `_settle_collaboration`** (swap the points ledger for cash)

Replace the points-based query/award in the loop with cash:

```python
        from app.services.cash_service import CashService
        from app.models.cash_transaction import CashTransaction, CashTransactionType
        # ... keep the FOR UPDATE lock + completers select unchanged ...
        shares = TaskTemplate.distribute_points(
            template.effective_points, len(completers) or 1
        )
        this_share_cents = 0
        for share, completer in zip(shares, completers):
            share_cents = int(share) * 100
            current = (
                await db.execute(
                    select(func.coalesce(func.sum(CashTransaction.amount_cents), 0))
                    .where(and_(
                        CashTransaction.assignment_id == completer.id,
                        CashTransaction.type == CashTransactionType.GIG_EARNED,
                    ))
                )
            ).scalar() or 0
            delta = share_cents - int(current)
            if delta != 0:
                await CashService.award_gig_cash(
                    db, completer.assigned_to, completer.family_id, completer.id,
                    delta,
                    description=(f"Collaboration gig split among {len(completers)} "
                                 f"— your share: ${share}.00 MXN"),
                )
            if completer.id == assignment.id:
                this_share_cents = share_cents
        return this_share_cents
```

- [ ] **Step 5: Run to verify pass** (run the whole economy + assignment suites)

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py tests/ -k "gig or assignment or collab" -v`
Expected: PASS. Fix any collaboration/gig test that asserted on `user.points` for gigs — those assertions move to `cash_cents` (× 100). Update them as part of this task.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/
git commit -m "feat(economy): gigs award cash (cents) instead of points; collaboration re-split on cash ledger"
```

---

## Task 7: Cash schemas + routes

**Files:**
- Create: `backend/app/schemas/cash.py`, `backend/app/api/routes/cash.py`
- Modify: `backend/app/main.py:15` (import), `:219` area (include_router)
- Test: `backend/tests/test_two_currency_economy.py` (route tests)

**Interfaces:**
- Routes (prefix `/api/cash`): `GET /balance` (self, kid), `GET /history` (self), `GET /family` (parent — all kids), `POST /{user_id}/payout` (parent), `POST /{user_id}/adjust` (parent).
- Consumes: `CashService`, `require_parent_role`, `get_current_user`, `to_uuid_required`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_two_currency_economy.py
@pytest.mark.asyncio
async def test_payout_route_parent_only_and_no_overdraw(client, db, test_family, test_parent_user, test_child_user):
    # give child cash directly
    test_child_user.cash_cents = 5000
    await db.commit()
    # auth as parent
    from app.core.security import create_access_token
    token = create_access_token({"sub": str(test_parent_user.id),
                                 "role": "parent",
                                 "family_id": str(test_family.id)})
    headers = {"Authorization": f"Bearer {token}"}
    # overdraw rejected
    r = await client.post(f"/api/cash/{test_child_user.id}/payout",
                          json={"amount_cents": 9999}, headers=headers)
    assert r.status_code == 400
    # partial ok
    r = await client.post(f"/api/cash/{test_child_user.id}/payout",
                          json={"amount_cents": 2000}, headers=headers)
    assert r.status_code == 200
    assert r.json()["new_balance_cents"] == 3000
```

(Verify `create_access_token`'s claim shape against `app/core/security.py` + `dependencies.py`; adjust the token payload keys to match `get_current_user`.)

- [ ] **Step 2: Run to verify fail** — Expected: 404 (route missing).

- [ ] **Step 3: Implement schemas**

```python
# backend/app/schemas/cash.py
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class CashSummary(BaseModel):
    user_id: UUID
    name: Optional[str] = None
    current_balance_cents: int
    total_earned_cents: int
    total_paid_cents: int


class CashTxn(BaseModel):
    id: UUID
    type: str
    amount_cents: int
    balance_after: int
    description: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class PayoutRequest(BaseModel):
    amount_cents: int = Field(..., gt=0)


class AdjustRequest(BaseModel):
    amount_cents: int
    reason: str = Field(..., min_length=1, max_length=200)


class PayoutResponse(BaseModel):
    success: bool
    new_balance_cents: int
    transaction_id: UUID
```

- [ ] **Step 4: Implement routes**

```python
# backend/app/api/routes/cash.py
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_parent_role
from app.core.type_utils import to_uuid_required
from app.core.exceptions import ValidationException
from app.models import User
from app.models.user import UserRole
from app.services.cash_service import CashService
from app.services.base_service import verify_user_in_family
from app.schemas.cash import CashSummary, CashTxn, PayoutRequest, AdjustRequest, PayoutResponse

router = APIRouter()


@router.get("/balance", response_model=CashSummary)
async def my_balance(current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    s = await CashService.get_summary(db, to_uuid_required(current_user.id))
    return CashSummary(user_id=current_user.id, name=current_user.name,
                       current_balance_cents=s["current_balance"],
                       total_earned_cents=s["total_earned"],
                       total_paid_cents=s["total_paid"])


@router.get("/history", response_model=List[CashTxn])
async def my_history(current_user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    rows = await CashService.get_history(db, to_uuid_required(current_user.id))
    return [CashTxn.model_validate(r) for r in rows]


@router.get("/family", response_model=List[CashSummary])
async def family_cash(current_user: User = Depends(require_parent_role),
                      db: AsyncSession = Depends(get_db)):
    fam = to_uuid_required(current_user.family_id)
    kids = (await db.execute(
        select(User).where(User.family_id == fam,
                           User.role.in_([UserRole.CHILD, UserRole.TEEN])))).scalars().all()
    out = []
    for k in kids:
        s = await CashService.get_summary(db, k.id)
        out.append(CashSummary(user_id=k.id, name=k.name,
                               current_balance_cents=s["current_balance"],
                               total_earned_cents=s["total_earned"],
                               total_paid_cents=s["total_paid"]))
    return out


@router.post("/{user_id}/payout", response_model=PayoutResponse)
async def payout(user_id: UUID, body: PayoutRequest,
                 current_user: User = Depends(require_parent_role),
                 db: AsyncSession = Depends(get_db)):
    fam = to_uuid_required(current_user.family_id)
    await verify_user_in_family(db, user_id, fam)
    try:
        tx = await CashService.record_payout(db, user_id, fam, body.amount_cents,
                                             to_uuid_required(current_user.id))
    except ValidationException as e:
        raise HTTPException(status_code=400, detail=str(e))
    bal = await CashService.get_balance(db, user_id)
    return PayoutResponse(success=True, new_balance_cents=bal, transaction_id=tx.id)


@router.post("/{user_id}/adjust", response_model=PayoutResponse)
async def adjust(user_id: UUID, body: AdjustRequest,
                 current_user: User = Depends(require_parent_role),
                 db: AsyncSession = Depends(get_db)):
    fam = to_uuid_required(current_user.family_id)
    await verify_user_in_family(db, user_id, fam)
    tx = await CashService.adjust(db, user_id, fam, body.amount_cents, body.reason,
                                  to_uuid_required(current_user.id))
    bal = await CashService.get_balance(db, user_id)
    return PayoutResponse(success=True, new_balance_cents=bal, transaction_id=tx.id)
```

- [ ] **Step 5: Register the router** in `backend/app/main.py`:
  - Add `cash` to the `from app.api.routes import ...` line (line 15).
  - Add near line 219: `app.include_router(cash.router, prefix="/api/cash", tags=["Cash"])`.

- [ ] **Step 6: Run to verify pass**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_two_currency_economy.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/cash.py backend/app/api/routes/cash.py backend/app/main.py backend/tests/test_two_currency_economy.py
git commit -m "feat(economy): /api/cash routes (balance, history, family, payout, adjust)"
```

---

## Task 8: Remove the dead points-conversion route

**Files:**
- Delete: `backend/app/api/routes/points_conversion.py`
- Modify: `backend/app/main.py:15` (drop from import), `:219` (drop include)

- [ ] **Step 1: Remove import + include**
  - In line 15, delete `points_conversion,` from the `from app.api.routes import ...` list.
  - Delete line `app.include_router(points_conversion.router, prefix="/api/points-conversion", ...)`.

- [ ] **Step 2: Delete the route file**

```bash
git rm backend/app/api/routes/points_conversion.py
```

- [ ] **Step 3: Verify app still imports + suite collects**

Run: `podman exec -e PYTHONPATH=/app family_app_backend python -c "import app.main"`
Then: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q`
Expected: imports clean; no collection errors referencing points_conversion.

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "chore(economy): remove dead points-conversion route (finance-api decommissioned + conflicts with two-currency model)"
```

---

## Task 9: Alembic migration

**Files:**
- Create: `backend/migrations/versions/2026_06_30_two_currency_economy.py`

**Interfaces:**
- `down_revision = "mcp_restricted_role"`.

- [ ] **Step 1: Write the migration**

```python
"""two-currency economy: cash_cents + cash_transactions; drop mandatory-zero-points check

Revision ID: two_currency_economy
Revises: mcp_restricted_role
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "two_currency_economy"
down_revision = "mcp_restricted_role"
branch_labels = None
depends_on = None


def upgrade():
    # 1. user cash balance
    op.add_column("users", sa.Column("cash_cents", sa.Integer(), nullable=False,
                                     server_default="0"))
    # 2. cash transaction type enum
    cash_type = postgresql.ENUM("gig_earned", "payout", "adjustment",
                                name="cashtransactiontype")
    cash_type.create(op.get_bind(), checkfirst=True)
    # 3. cash_transactions table
    op.create_table(
        "cash_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", cash_type, nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("balance_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("gig_claim_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("gig_claims.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_cash_transactions_user_id", "cash_transactions", ["user_id"])
    op.create_index("ix_cash_transactions_family_id", "cash_transactions", ["family_id"])
    op.create_index("ix_cash_transactions_type", "cash_transactions", ["type"])
    op.create_index("ix_cash_transactions_created_at", "cash_transactions", ["created_at"])
    # 4. drop the mandatory-zero-points check
    op.drop_constraint("chk_mandatory_zero_points", "task_templates", type_="check")


def downgrade():
    op.create_check_constraint("chk_mandatory_zero_points", "task_templates",
                               "is_bonus = true OR points = 0")
    op.drop_index("ix_cash_transactions_created_at", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_type", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_family_id", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_user_id", table_name="cash_transactions")
    op.drop_table("cash_transactions")
    postgresql.ENUM(name="cashtransactiontype").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "cash_cents")
```

- [ ] **Step 2: Verify upgrade runs against a scratch DB**

Run (local dev DB or a throwaway): `podman exec family_app_backend alembic upgrade head`
Then downgrade one and back up:
`podman exec family_app_backend alembic downgrade -1 && podman exec family_app_backend alembic upgrade head`
Expected: both directions clean, no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/2026_06_30_two_currency_economy.py
git commit -m "feat(economy): migration — cash_cents + cash_transactions, drop chk_mandatory_zero_points"
```

---

## Task 10: Jarvis Gemini-safe schema test (fix already in tree)

**Files:**
- Modify (already done, uncommitted): `backend/app/mcp/openai_bridge.py`
- Test: `backend/tests/test_openai_bridge_gemini_safe.py`

**Interfaces:**
- Consumes: `mcp_tools_to_openai`, `_gemini_safe`.

- [ ] **Step 1: Write the test**

```python
# backend/tests/test_openai_bridge_gemini_safe.py
from app.mcp.openai_bridge import _gemini_safe, mcp_tools_to_openai


def _arrays_have_typed_items(node) -> bool:
    """True if every array node has items with a usable type."""
    if isinstance(node, dict):
        if node.get("type") == "array":
            it = node.get("items")
            if not (isinstance(it, dict) and (it.get("type") or it.get("anyOf")
                    or it.get("any_of") or it.get("properties") or it.get("$ref"))):
                return False
        return all(_arrays_have_typed_items(v) for v in node.values())
    if isinstance(node, list):
        return all(_arrays_have_typed_items(x) for x in node)
    return True


def test_empty_items_array_gets_typed():
    schema = {"type": "object", "properties": {
        "conditions": {"anyOf": [{"type": "array", "items": {}}, {"type": "null"}]}}}
    out = _gemini_safe(schema)
    assert _arrays_have_typed_items(out)
    assert out["properties"]["conditions"]["anyOf"][0]["items"]["type"] == "string"


def test_missing_items_array_gets_typed():
    out = _gemini_safe({"type": "array"})
    assert out["items"]["type"] == "string"


def test_typed_items_untouched():
    out = _gemini_safe({"type": "array", "items": {"type": "integer"}})
    assert out["items"]["type"] == "integer"


def test_real_mcp_tools_all_gemini_safe():
    import asyncio
    from mcp.shared.memory import create_connected_server_and_client_session
    from app.mcp.server import server as mcp_server

    async def _tools():
        async with create_connected_server_and_client_session(mcp_server) as s:
            await s.initialize()
            return (await s.list_tools()).tools

    tools = asyncio.get_event_loop().run_until_complete(_tools())
    converted = mcp_tools_to_openai(tools)
    for t in converted:
        assert _arrays_have_typed_items(t["function"]["parameters"]), t["function"]["name"]
```

- [ ] **Step 2: Run to verify pass** (fix is already implemented)

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_openai_bridge_gemini_safe.py -v`
Expected: PASS (4 tests). If `test_real_mcp_tools_all_gemini_safe` has event-loop issues under pytest-asyncio, mark it `@pytest.mark.asyncio` and `await` instead.

- [ ] **Step 3: Commit**

```bash
git add backend/app/mcp/openai_bridge.py backend/tests/test_openai_bridge_gemini_safe.py
git commit -m "fix(jarvis): sanitize MCP tool schemas for Gemini strict validation (array items) + test"
```

---

## Task 11: Frontend — kid dashboard dual balance

**Files:**
- Modify: kid dashboard page (find it: `grep -rln "points" frontend/src/pages/kid frontend/src/pages/child 2>/dev/null` or the kid home under `frontend/src/pages/`). Likely `frontend/src/pages/index.astro` / a kid dashboard component.
- Modify: any balance fetch to also call `GET /api/cash/balance`.

- [ ] **Step 1: Locate the kid balance display**

```bash
grep -rln "points" frontend/src/pages frontend/src/components | xargs grep -l "balance\|puntos\|points" | head
```

- [ ] **Step 2: Add a cash balance card** next to the points card. Fetch `/api/cash/balance` (SSR, internal `http://backend:8000`, cookie auth like other calls). Show:
  - ⭐ Puntos: `{points}` (privilegios)
  - 💵 Cash: `${(cash_cents/100).toFixed(2)} MXN` (pendiente de pago)

- [ ] **Step 3: Manual verify** — load kid dashboard, both balances render; complete a chore → points go up; gig approved → cash goes up.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/...
git commit -m "feat(economy/ui): kid dashboard shows points + cash balances"
```

---

## Task 12: Frontend — gig board + task cards labels

**Files:**
- Modify: gig board page(s) under `frontend/src/pages/` (`grep -rln "gig" frontend/src/pages`), task cards (`TaskCreateModal.astro` renderTemplateCard, task list).

- [ ] **Step 1:** Gig values display as `$N MXN` (cash); chore values display as `+N pts`.
- [ ] **Step 2:** In `TaskCreateModal.astro` the points field label: when **Bonus** on → "Valor en $ (cash)"; when off → "Puntos (privilegios)". (Optional polish; the field already works for both after Task 2.)
- [ ] **Step 3: Manual verify** in the running app.
- [ ] **Step 4: Commit**

```bash
git commit -am "feat(economy/ui): gig board shows cash $, chores show points"
```

---

## Task 13: Frontend — parent payout screen + remove PointsConverter

**Files:**
- Create: `frontend/src/pages/parent/payouts.astro`
- Delete: `frontend/src/components/PointsConverter.astro`, `frontend/src/pages/api/points/convert.ts`
- Modify: parent nav (add Payouts link); remove any `PointsConverter` import/usage.

- [ ] **Step 1: Find PointsConverter usages**

```bash
grep -rln "PointsConverter\|points/convert\|points-conversion" frontend/src
```

- [ ] **Step 2: Build the payout page** — fetch `GET /api/cash/family`; list each kid with `balance / earned / paid`; a "Pagar" form posting `POST /api/cash/{id}/payout` (full or partial amount in pesos → ×100 cents). Show payout history (optional: `GET /api/cash/history` per kid).
- [ ] **Step 3: Remove** PointsConverter component + its `convert.ts` proxy + any import. Add a Payouts entry to parent nav.
- [ ] **Step 4: Manual verify** — parent pays a kid full/partial; balance drops; overdraw shows error.
- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(economy/ui): parent payout screen; remove dead PointsConverter"
```

---

## Task 14: Full suite + live verification

- [ ] **Step 1: Full backend suite**

Run: `podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q`
Expected: all green. Fix any pre-existing gig/points test that asserted gig→points (now gig→cash).

- [ ] **Step 2: requesting-code-review** on the full diff (superpowers:requesting-code-review).

- [ ] **Step 3: Deploy** (`./scripts/deploy-gcp.sh -y` after `gcloud auth login`). Runs alembic upgrade on prod.

- [ ] **Step 4: Live verify on prod**
  - Create a mandatory task with points → 200 (no 422).
  - Jarvis chat returns a real reply (no Gemini 400).
  - Complete a chore → kid points up; approve a gig → kid cash up; parent payout → cash down.

- [ ] **Step 5: Final commit / PR**

```bash
git push -u origin feat/two-currency-economy
gh pr create --fill
```

---

## Self-Review

- **Spec coverage:** §1 data model → T1, T9. §2 earning rules → T2 (validator/constraint), T4-T5 (chore points), T6 (gig cash). §3 payout → T3, T7. §4 API → T3, T7. §5 frontend → T11-T13. §6 cleanup/migration → T8, T9. §7 testing → tests in every task + T14. Jarvis (related) → T10. All covered.
- **Placeholder scan:** Frontend tasks (T11-T13) intentionally use "locate the file" steps because exact kid-dashboard/gig-board paths weren't read during planning; each has a concrete `grep` to find the target and concrete edit intent. Backend tasks have full code.
- **Type consistency:** `award_gig_cash(db, user_id, family_id, assignment_id, amount_cents, description=None)` used consistently in T3, T6. `_award_assignment` now returns **cents** (T6) — callers' display text updated in T6 Step 3. `CashService.get_summary` keys (`current_balance/total_earned/total_paid`) consumed in T7 routes.
- **Risk note:** T6 changes the meaning of `_award_assignment`'s return (pts→cents); existing tests asserting gig→`user.points` must move to `cash_cents` (×100). Called out in T6 Step 5 and T14 Step 1.
