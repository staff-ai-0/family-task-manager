# First-Run Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-blocking onboarding checklist to the parent dashboard that auto-advances through 4 steps (child invited, task created, reward created, first points awarded) and permanently dismisses once complete.

**Architecture:** 5 boolean columns on `families` table track completion; `OnboardingService.advance()` is wired as fire-and-forget in existing services; `GET/POST /api/families/onboarding` expose state and dismiss; the parent dashboard renders a collapsible widget server-side.

**Tech Stack:** Python 3.12 + SQLAlchemy async + Alembic, Astro 5 + Tailwind CSS v4, FastAPI, PostgreSQL 15.

---

## File Map

**Create:**
- `backend/migrations/versions/2026_06_10_onboarding_columns.py` — Alembic migration
- `backend/app/schemas/onboarding.py` — `OnboardingState` Pydantic schema
- `backend/app/services/onboarding_service.py` — `OnboardingService`
- `backend/app/api/routes/onboarding.py` — 2 routes (GET state, POST dismiss)
- `frontend/src/pages/api/families/onboarding.ts` — SSR proxy for the 2 routes
- `backend/tests/test_onboarding.py` — 8 tests

**Modify:**
- `backend/app/models/family.py` — add 5 columns
- `backend/app/main.py` — register onboarding router
- `backend/app/services/task_template_service.py` — advance `task_created`
- `backend/app/services/reward_service.py` — advance `reward_created`
- `backend/app/services/gig_claim_service.py` — advance `points_awarded` (×2 paths)
- `backend/app/services/task_assignment_service.py` — advance `points_awarded` (×2 paths)
- `backend/app/api/routes/auth.py` — advance `child_invited` on family join
- `frontend/src/pages/parent/index.astro` — add checklist widget
- `frontend/src/pages/parent/tasks.astro` — enhanced empty state
- `frontend/src/pages/rewards.astro` — enhanced empty state (parent view)

---

## Codebase Context

**Key patterns to follow:**
- `backend/app/services/reward_goal_service.py` — fire-and-forget try/except pattern used in hooks
- `backend/app/api/routes/oversight.py` — route pattern with `require_parent_role` dep
- `frontend/src/pages/api/families/me.ts` — proxy pattern to copy for the new onboarding proxy
- `backend/app/models/family.py` — Family ORM model (add 5 columns here)
- Alembic revision chain: `user_reward_goals` is the current head (`backend/migrations/versions/2026_06_09_add_user_reward_goals.py`)

**Import paths:**
- `from app.core.dependencies import require_parent_role, get_db`
- `from app.core.type_utils import to_uuid_required`
- `from app.models.family import Family`
- `from sqlalchemy import update`

---

## Task 1: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/2026_06_10_onboarding_columns.py`
- Modify: `backend/app/models/family.py`

- [ ] **Step 1: Add 5 columns to the Family ORM model**

Open `backend/app/models/family.py`. After the `is_active` line (line 28), add:

```python
# Onboarding checklist — tracked per family, all False on creation.
onboarding_child_invited = Column(Boolean, nullable=False, default=False, server_default="false")
onboarding_task_created = Column(Boolean, nullable=False, default=False, server_default="false")
onboarding_reward_created = Column(Boolean, nullable=False, default=False, server_default="false")
onboarding_points_awarded = Column(Boolean, nullable=False, default=False, server_default="false")
onboarding_dismissed = Column(Boolean, nullable=False, default=False, server_default="false")
```

`Boolean` is already imported in this file.

- [ ] **Step 2: Create the migration file**

Create `backend/migrations/versions/2026_06_10_onboarding_columns.py`:

```python
"""add onboarding columns to families

Revision ID: onboarding_columns
Revises: user_reward_goals
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'onboarding_columns'
down_revision = 'user_reward_goals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in [
        'onboarding_child_invited',
        'onboarding_task_created',
        'onboarding_reward_created',
        'onboarding_points_awarded',
        'onboarding_dismissed',
    ]:
        op.add_column(
            'families',
            sa.Column(col, sa.Boolean(), nullable=False, server_default='false'),
        )


def downgrade() -> None:
    for col in [
        'onboarding_dismissed',
        'onboarding_points_awarded',
        'onboarding_reward_created',
        'onboarding_task_created',
        'onboarding_child_invited',
    ]:
        op.drop_column('families', col)
```

- [ ] **Step 3: Run migration (inside backend container)**

```bash
podman exec family_app_backend alembic upgrade head
```

Expected output ends with:
```
Running upgrade user_reward_goals -> onboarding_columns, add onboarding columns to families
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/family.py backend/migrations/versions/2026_06_10_onboarding_columns.py
git commit -m "feat(onboarding): add 5 onboarding columns to families table"
```

---

## Task 2: OnboardingService and Schema

**Files:**
- Create: `backend/app/schemas/onboarding.py`
- Create: `backend/app/services/onboarding_service.py`

- [ ] **Step 1: Write the failing tests first**

Create `backend/tests/test_onboarding.py` with just the service-level tests (routes tested in Task 3):

```python
"""OnboardingService — unit tests."""
import pytest
from uuid import uuid4

from app.services.onboarding_service import OnboardingService


@pytest.mark.asyncio
async def test_get_state_all_false(db_session, test_family):
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.child_invited is False
    assert state.task_created is False
    assert state.reward_created is False
    assert state.points_awarded is False
    assert state.dismissed is False
    assert state.all_done is False


@pytest.mark.asyncio
async def test_advance_sets_flag(db_session, test_family):
    await OnboardingService.advance(test_family.id, "task_created", db_session)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.task_created is True


@pytest.mark.asyncio
async def test_advance_idempotent(db_session, test_family):
    await OnboardingService.advance(test_family.id, "reward_created", db_session)
    await OnboardingService.advance(test_family.id, "reward_created", db_session)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.reward_created is True  # no error, stays True


@pytest.mark.asyncio
async def test_all_done_computed(db_session, test_family):
    for step in ["child_invited", "task_created", "reward_created", "points_awarded"]:
        await OnboardingService.advance(test_family.id, step, db_session)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.all_done is True


@pytest.mark.asyncio
async def test_dismiss(db_session, test_family):
    await OnboardingService.dismiss(test_family.id, db_session)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.dismissed is True
```

- [ ] **Step 2: Run to confirm they fail**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: 5 failures with `ImportError: cannot import name 'OnboardingService'`.

- [ ] **Step 3: Create the schema**

Create `backend/app/schemas/onboarding.py`:

```python
from pydantic import BaseModel, model_validator


class OnboardingState(BaseModel):
    child_invited: bool
    task_created: bool
    reward_created: bool
    points_awarded: bool
    dismissed: bool
    all_done: bool = False

    @model_validator(mode="after")
    def compute_all_done(self) -> "OnboardingState":
        self.all_done = all([
            self.child_invited,
            self.task_created,
            self.reward_created,
            self.points_awarded,
        ])
        return self

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Create the service**

Create `backend/app/services/onboarding_service.py`:

```python
"""OnboardingService — track first-run checklist completion per family."""
import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.schemas.onboarding import OnboardingState

log = logging.getLogger(__name__)

VALID_STEPS = frozenset([
    "child_invited", "task_created", "reward_created", "points_awarded",
])


class OnboardingService:

    @staticmethod
    async def advance(family_id: UUID, step: str, db: AsyncSession) -> None:
        """Set onboarding_{step}=True idempotently. Caller must commit."""
        if step not in VALID_STEPS:
            log.warning("OnboardingService.advance: unknown step %r", step)
            return
        col = f"onboarding_{step}"
        await db.execute(
            update(Family)
            .where(Family.id == family_id, getattr(Family, col).is_(False))
            .values({col: True})
        )

    @staticmethod
    async def get_state(family_id: UUID, db: AsyncSession) -> OnboardingState:
        row = await db.get(Family, family_id)
        if not row:
            return OnboardingState(
                child_invited=False, task_created=False,
                reward_created=False, points_awarded=False,
                dismissed=False,
            )
        return OnboardingState(
            child_invited=row.onboarding_child_invited,
            task_created=row.onboarding_task_created,
            reward_created=row.onboarding_reward_created,
            points_awarded=row.onboarding_points_awarded,
            dismissed=row.onboarding_dismissed,
        )

    @staticmethod
    async def dismiss(family_id: UUID, db: AsyncSession) -> None:
        await db.execute(
            update(Family)
            .where(Family.id == family_id)
            .values(onboarding_dismissed=True)
        )
        await db.commit()
```

- [ ] **Step 5: Run tests — expect pass**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/onboarding.py backend/app/services/onboarding_service.py backend/tests/test_onboarding.py
git commit -m "feat(onboarding): OnboardingService + schema + unit tests"
```

---

## Task 3: Backend Routes and Frontend Proxy

**Files:**
- Create: `backend/app/api/routes/onboarding.py`
- Modify: `backend/app/main.py` (register router)
- Create: `frontend/src/pages/api/families/onboarding.ts`

- [ ] **Step 1: Add route tests to test_onboarding.py**

Append to `backend/tests/test_onboarding.py`:

```python
# ── Route tests ──────────────────────────────────────────────────────────────

import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def parent_client(client, test_parent_user, db_session):
    """Authenticated client for test_parent_user."""
    r = await client.post("/api/auth/login", json={
        "email": "parent@test.com", "password": "password123",
    })
    assert r.status_code == 200
    return client


@pytest.mark.asyncio
async def test_get_onboarding_state(parent_client, test_family):
    r = await parent_client.get("/api/families/onboarding")
    assert r.status_code == 200
    data = r.json()
    assert "task_created" in data
    assert data["all_done"] is False


@pytest.mark.asyncio
async def test_dismiss_onboarding(parent_client, test_family):
    r = await parent_client.post("/api/families/onboarding/dismiss")
    assert r.status_code == 204
    r2 = await parent_client.get("/api/families/onboarding")
    assert r2.json()["dismissed"] is True


@pytest.mark.asyncio
async def test_onboarding_requires_parent(client, test_teen_user, db_session):
    r = await client.post("/api/auth/login", json={
        "email": "teen@test.local", "password": "password123",
    })
    assert r.status_code == 200
    r2 = await client.get("/api/families/onboarding")
    assert r2.status_code == 403
```

- [ ] **Step 2: Run new tests — expect fail**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py::test_get_onboarding_state tests/test_onboarding.py::test_dismiss_onboarding tests/test_onboarding.py::test_onboarding_requires_parent -v --no-cov
```

Expected: 3 failures with 404 (router not registered yet).

- [ ] **Step 3: Create the routes file**

Create `backend/app/api/routes/onboarding.py`:

```python
"""Onboarding checklist routes — GET state, POST dismiss."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_parent_role
from app.core.type_utils import to_uuid_required
from app.models.user import User
from app.schemas.onboarding import OnboardingState
from app.services.onboarding_service import OnboardingService

router = APIRouter()


@router.get("", response_model=OnboardingState)
async def get_onboarding_state(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    return await OnboardingService.get_state(family_id, db)


@router.post("/dismiss", status_code=204)
async def dismiss_onboarding(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    family_id = to_uuid_required(current_user.family_id)
    await OnboardingService.dismiss(family_id, db)
    return Response(status_code=204)
```

- [ ] **Step 4: Register the router in main.py**

Open `backend/app/main.py`. At line 15, add `onboarding` to the existing import:

```python
from app.api.routes import (
    auth, users, rewards, consequences, families, task_templates,
    task_assignments, sync, oauth, payment, points_conversion,
    invitations, subscriptions, push, shopping, calendar, notifications,
    kiosk, pet, analytics, frankie, meals, family_chat, frankie_schedules,
    dm, budget, budget_accounts, budget_transactions, budget_categories,
    budget_allocations, budget_payees, budget_goals, budget_reports,
    budget_custom_reports, budget_recurring_transactions,
    budget_recycle_bin, budget_saved_filters, budget_tags,
    budget_receipt_drafts, budget_transfers, budget_months,
    budget_categorization_rules, budget_import_export, gigs, oversight,
    onboarding,
)
```

Find the line that includes the oversight router (near line 159):
```python
app.include_router(oversight.router, prefix="/api/oversight", tags=["Oversight"])
```
Add after it:
```python
app.include_router(onboarding.router, prefix="/api/families/onboarding", tags=["Onboarding"])
```

- [ ] **Step 5: Run route tests — expect pass**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: all 8 tests pass.

- [ ] **Step 6: Create the frontend proxy**

Create `frontend/src/pages/api/families/onboarding.ts`:

```typescript
import type { APIRoute } from "astro";

const API = () =>
    process.env.API_BASE_URL ||
    process.env.PUBLIC_API_BASE_URL ||
    "http://backend:8000";

function unauthorized() {
    return new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
    });
}

export const GET: APIRoute = async ({ cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    try {
        const r = await fetch(`${API()}/api/families/onboarding`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(await r.text(), {
            status: r.status,
            headers: { "Content-Type": "application/json" },
        });
    } catch (e) {
        console.error("families/onboarding GET error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502, headers: { "Content-Type": "application/json" },
        });
    }
};

export const POST: APIRoute = async ({ request, cookies }) => {
    const token = cookies.get("access_token")?.value;
    if (!token) return unauthorized();
    const url = new URL(request.url);
    const backendPath = url.pathname.replace("/api", "");
    try {
        const r = await fetch(`${API()}${backendPath}`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        return new Response(null, { status: r.status });
    } catch (e) {
        console.error("families/onboarding POST error:", e);
        return new Response(JSON.stringify({ detail: "Upstream error" }), {
            status: 502, headers: { "Content-Type": "application/json" },
        });
    }
};
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/onboarding.py backend/app/main.py backend/tests/test_onboarding.py frontend/src/pages/api/families/onboarding.ts
git commit -m "feat(onboarding): routes GET /api/families/onboarding + POST /dismiss + frontend proxy"
```

---

## Task 4: Hook Wiring — task_created and reward_created

**Files:**
- Modify: `backend/app/services/task_template_service.py:94-97`
- Modify: `backend/app/services/reward_service.py:51-53`

The fire-and-forget pattern: call `OnboardingService.advance`, then `await db.commit()` to persist the flag, inside a try/except that logs and never blocks the main operation.

- [ ] **Step 1: Wire task_created hook in task_template_service.py**

In `backend/app/services/task_template_service.py`, locate the end of `create_template` (around line 94-97):

```python
        db.add(template)
        await db.commit()
        await db.refresh(template)
        return template
```

Replace with:

```python
        db.add(template)
        await db.commit()
        await db.refresh(template)
        try:
            from app.services.onboarding_service import OnboardingService
            await OnboardingService.advance(family_id, "task_created", db)
            await db.commit()
        except Exception:
            logger.warning("onboarding advance task_created failed", exc_info=True)
        return template
```

(The file already has `logger = logging.getLogger(__name__)` at the top.)

- [ ] **Step 2: Wire reward_created hook in reward_service.py**

In `backend/app/services/reward_service.py`, locate the end of `create_reward` (around line 51-53):

```python
        db.add(reward)
        await db.commit()
        await db.refresh(reward)
        return reward
```

Replace with:

```python
        db.add(reward)
        await db.commit()
        await db.refresh(reward)
        try:
            import logging
            from app.services.onboarding_service import OnboardingService
            await OnboardingService.advance(family_id, "reward_created", db)
            await db.commit()
        except Exception:
            logging.getLogger(__name__).warning(
                "onboarding advance reward_created failed", exc_info=True
            )
        return reward
```

- [ ] **Step 3: Run existing reward + template tests to confirm no regression**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_rewards.py tests/test_task_templates.py -v --no-cov 2>&1 | tail -10
```

Expected: all pass (same count as before).

- [ ] **Step 4: Add integration assertions to test_onboarding.py**

Append to `backend/tests/test_onboarding.py`:

```python
# ── Hook integration tests ───────────────────────────────────────────────────
from app.services.task_template_service import TaskTemplateService
from app.schemas.task_template import TaskTemplateCreate


@pytest.mark.asyncio
async def test_advance_task_created_via_hook(
    db_session, test_family, test_parent_user,
):
    data = TaskTemplateCreate(
        title="Clean room",
        points=10,
        effort_level="low",
        interval_days=7,
        assignment_type="any",
        is_bonus=False,
    )
    await TaskTemplateService.create_template(
        db_session, data, test_family.id, test_parent_user.id,
    )
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.task_created is True


@pytest.mark.asyncio
async def test_advance_reward_created_via_hook(
    db_session, test_family, test_parent_user,
):
    from app.services.reward_service import RewardService
    from app.schemas.reward import RewardCreate
    from app.models.reward import RewardCategory

    data = RewardCreate(
        title="Extra screen time",
        points_cost=50,
        category=RewardCategory.SCREEN_TIME,
        icon="🎮",
    )
    await RewardService.create_reward(db_session, data, test_family.id)
    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.reward_created is True
```

- [ ] **Step 5: Run new tests**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: all 10 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/task_template_service.py backend/app/services/reward_service.py backend/tests/test_onboarding.py
git commit -m "feat(onboarding): wire task_created + reward_created hooks"
```

---

## Task 5: Hook Wiring — points_awarded (4 paths)

**Files:**
- Modify: `backend/app/services/gig_claim_service.py` (×2 locations)
- Modify: `backend/app/services/task_assignment_service.py` (×2 locations)

Points are awarded in 4 places. Add the same fire-and-forget pattern after each existing `db.commit()` that credits points. All 4 spots already have a `check_nudge` try/except block nearby — add the onboarding hook in the same pattern.

- [ ] **Step 1: Wire gig_claim_service.py — auto-approve path**

In `backend/app/services/gig_claim_service.py`, find the auto-approve block (inside the `complete` method, around line 123 — `await db.commit()` that follows `claim.status = GigClaimStatus.APPROVED`). After that commit and before the existing `check_nudge` try/except:

```python
            await db.commit()
            await db.refresh(claim)
            await GigClaimService._notify_claimer_approved(
                db, claim, offering, points, auto=True
            )
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(claim.family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            try:
                from app.services.reward_goal_service import RewardGoalService
                ...
```

- [ ] **Step 2: Wire gig_claim_service.py — parent approve path**

In `backend/app/services/gig_claim_service.py`, find the parent approval block (inside the `approve` method, around line 351 — `await db.commit()` that follows `claim.status = GigClaimStatus.APPROVED`). After that commit and before the existing `check_nudge` try/except:

```python
            await db.commit()
            await db.refresh(claim)
            await GigClaimService._notify_claimer_approved(
                db, claim, offering, points, auto=False
            )
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            try:
                from app.services.reward_goal_service import RewardGoalService
                ...
```

- [ ] **Step 3: Wire task_assignment_service.py — auto-approve path**

In `backend/app/services/task_assignment_service.py`, find the `if auto_approved:` block (around line 715) that already calls `check_nudge`. Add the onboarding advance **inside** the same try/except block just before the `check_nudge` call:

Current block (lines ~715-729):
```python
        if auto_approved:
            try:
                from app.services.reward_goal_service import RewardGoalService
                refreshed = await get_user_by_id(db, user_id)
                await RewardGoalService.check_nudge(...)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after task auto-approve failed", exc_info=True
                )
```

Replace with:

```python
        if auto_approved:
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            try:
                from app.services.reward_goal_service import RewardGoalService
                refreshed = await get_user_by_id(db, user_id)
                await RewardGoalService.check_nudge(
                    user_id=user_id,
                    family_id=family_id,
                    new_balance=refreshed.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after task auto-approve failed", exc_info=True
                )
```

- [ ] **Step 4: Wire task_assignment_service.py — approve_gig path**

In `backend/app/services/task_assignment_service.py`, inside `approve_gig`, after the line `await db.commit()` (around line 931, right after `PetService.on_task_completed`) and before the `NotificationService.create` call:

```python
            await db.commit()
            try:
                from app.services.onboarding_service import OnboardingService
                await OnboardingService.advance(family_id, "points_awarded", db)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "onboarding advance points_awarded failed", exc_info=True
                )
            # NotificationService.create commits + fans out push.
            await NotificationService.create(
                ...
```

- [ ] **Step 5: Run existing gig + assignment tests to check no regression**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_gig_gating.py tests/test_task_assignment_service.py -v --no-cov 2>&1 | tail -10
```

Expected: same pass/fail count as before this task (all previously-passing tests still pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gig_claim_service.py backend/app/services/task_assignment_service.py
git commit -m "feat(onboarding): wire points_awarded hook across 4 approval paths"
```

---

## Task 6: Hook Wiring — child_invited

**Files:**
- Modify: `backend/app/api/routes/auth.py`

`child_invited` fires when a new user joins an existing family (i.e., `data.family_code` was provided in the registration payload). The `await db.commit()` at line ~135 covers both new-family and join-existing paths; add the hook after it, guarded by `if data.family_code:`.

- [ ] **Step 1: Wire child_invited in auth.py**

In `backend/app/api/routes/auth.py`, find the `register_family` function. After `await db.commit()` and `await db.refresh(user)` (around lines 135-136), add:

```python
    await db.commit()
    await db.refresh(user)

    if data.family_code:
        try:
            from app.services.onboarding_service import OnboardingService
            from uuid import UUID as _UUID
            await OnboardingService.advance(family.id, "child_invited", db)
            await db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "onboarding advance child_invited failed", exc_info=True
            )
```

- [ ] **Step 2: Run auth tests**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_auth.py -v --no-cov 2>&1 | tail -10
```

Expected: all previously-passing auth tests still pass.

- [ ] **Step 3: Add hook test to test_onboarding.py**

Append to `backend/tests/test_onboarding.py`:

```python
@pytest.mark.asyncio
async def test_advance_child_invited_via_join(client, test_family, db_session):
    """Registering with a family_code advances child_invited."""
    from app.models.family import Family
    from sqlalchemy import select
    fam = (await db_session.execute(
        select(Family).where(Family.id == test_family.id)
    )).scalar_one()
    join_code = fam.join_code

    r = await client.post("/api/auth/register", json={
        "email": "newchild@test.com",
        "name": "New Child",
        "password": "password123",
        "family_code": join_code,
    })
    assert r.status_code in (200, 201)

    state = await OnboardingService.get_state(test_family.id, db_session)
    assert state.child_invited is True
```

- [ ] **Step 4: Run new test**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py::test_advance_child_invited_via_join -v --no-cov
```

Expected: PASS.

- [ ] **Step 5: Run full onboarding test suite**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: all tests pass (now 13 total).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/auth.py backend/tests/test_onboarding.py
git commit -m "feat(onboarding): wire child_invited hook on family join"
```

---

## Task 7: Parent Dashboard Checklist Widget

**Files:**
- Modify: `frontend/src/pages/parent/index.astro`

The widget fetches onboarding state server-side during SSR. It renders above the existing tile grid. If `dismissed=true`, it's not rendered at all (no flash). The × dismiss button calls `POST /api/families/onboarding/dismiss` client-side and removes the widget from DOM.

- [ ] **Step 1: Add SSR data fetch for onboarding state**

In `frontend/src/pages/parent/index.astro`, find the existing parallel fetches at the top of the frontmatter (around line 20 where `oversight` is fetched). Add the onboarding fetch to the same block:

```typescript
const [{ data: oversight }, { data: onboarding }] = await Promise.all([
    apiFetch<any>("/api/oversight/summary", { token }),
    apiFetch<any>("/api/families/onboarding", { token }),
]);
```

(Replace the existing `const { data: oversight } = await apiFetch...` with this parallel form.)

- [ ] **Step 2: Add the widget HTML**

In `frontend/src/pages/parent/index.astro`, find `<main class="flex-1 px-4 py-6">`. Insert the widget as the first child inside `<main>`, before the existing tile grid:

```astro
{!onboarding?.dismissed && (
    <div id="onboarding-widget" class="mb-6 bg-brand-coral/10 border border-brand-coral/20 rounded-2xl p-5 shadow-[var(--shadow-card)]">
        <div class="flex items-center justify-between mb-3">
            <h2 class="font-bold text-brand-ink text-base">
                {lang === "es" ? "¡Empecemos! 🚀" : "Getting Started 🚀"}
            </h2>
            {onboarding?.all_done && (
                <button
                    id="dismiss-onboarding"
                    class="text-brand-ink-soft hover:text-brand-ink transition-colors text-lg leading-none"
                    aria-label="Dismiss"
                >×</button>
            )}
        </div>
        <ol class="space-y-2 text-sm">
            <li class="flex items-center gap-3">
                <span class={onboarding?.task_created ? "text-green-600" : "text-brand-ink-soft"}>
                    {onboarding?.task_created ? "✅" : "◻"}
                </span>
                <span class={onboarding?.task_created ? "line-through text-brand-ink-soft" : "text-brand-ink"}>
                    {lang === "es" ? "Crea tu primera tarea" : "Create your first task"}
                </span>
                {!onboarding?.task_created && (
                    <a href="/parent/tasks" class="ml-auto text-brand-sky-deep font-semibold hover:underline">→</a>
                )}
            </li>
            <li class="flex items-center gap-3">
                <span class={onboarding?.reward_created ? "text-green-600" : "text-brand-ink-soft"}>
                    {onboarding?.reward_created ? "✅" : "◻"}
                </span>
                <span class={onboarding?.reward_created ? "line-through text-brand-ink-soft" : "text-brand-ink"}>
                    {lang === "es" ? "Crea una recompensa" : "Create a reward"}
                </span>
                {!onboarding?.reward_created && (
                    <a href="/rewards" class="ml-auto text-brand-sky-deep font-semibold hover:underline">→</a>
                )}
            </li>
            <li class="flex items-center gap-3">
                <span class={onboarding?.child_invited ? "text-green-600" : "text-brand-ink-soft"}>
                    {onboarding?.child_invited ? "✅" : "◻"}
                </span>
                <span class={onboarding?.child_invited ? "line-through text-brand-ink-soft" : "text-brand-ink"}>
                    {lang === "es" ? "Invita a un hijo/a" : "Invite a child"}
                </span>
                {!onboarding?.child_invited && (
                    <a href="/parent/invite" class="ml-auto text-brand-sky-deep font-semibold hover:underline">→</a>
                )}
            </li>
            <li class="flex items-center gap-3">
                <span class={onboarding?.points_awarded ? "text-green-600" : "text-brand-ink-soft"}>
                    {onboarding?.points_awarded ? "✅" : "◻"}
                </span>
                <span class={onboarding?.points_awarded ? "line-through text-brand-ink-soft" : "text-brand-ink"}>
                    {lang === "es" ? "Aprueba la primera tarea" : "Approve first task"}
                </span>
                {onboarding?.all_done && !onboarding?.points_awarded && (
                    <a href="/parent/approvals" class="ml-auto text-brand-sky-deep font-semibold hover:underline">→</a>
                )}
            </li>
        </ol>
        {onboarding?.all_done && (
            <p class="mt-3 text-sm text-green-700 font-semibold">
                {lang === "es" ? "🎉 ¡Todo listo! Tu familia está en marcha." : "🎉 All set! Your family is up and running."}
            </p>
        )}
    </div>
)}
```

- [ ] **Step 3: Add dismiss script**

In `frontend/src/pages/parent/index.astro`, find the closing `</Layout>` tag and add before it:

```html
<script>
    document.getElementById("dismiss-onboarding")?.addEventListener("click", async () => {
        await fetch("/api/families/onboarding/dismiss", { method: "POST" });
        document.getElementById("onboarding-widget")?.remove();
    });
</script>
```

- [ ] **Step 4: Verify in browser**

Start the dev stack (`podman compose up -d`) and visit `http://localhost:3003/parent`. Log in as `parent@demo.com / password123` (or any parent in a new family). Confirm:
- Widget renders with all 4 steps unchecked
- Steps have → links pointing to correct pages
- Widget does NOT render for an already-dismissed state

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent/index.astro
git commit -m "feat(onboarding): parent dashboard checklist widget"
```

---

## Task 8: Empty States on Tasks and Rewards Pages

**Files:**
- Modify: `frontend/src/pages/parent/tasks.astro:179-181`
- Modify: `frontend/src/pages/rewards.astro` (find `rewards.length === 0` block)

Both pages already have a `length === 0` check that shows a plain text message. Replace with a card-style empty state that includes a CTA button.

- [ ] **Step 1: Update tasks page empty state**

In `frontend/src/pages/parent/tasks.astro`, find the block (around line 179-181):

```astro
{templateList.length === 0 ? (
    <p class="text-brand-ink-soft text-sm text-center py-6">{t(lang, "pt_none")}</p>
) : (
```

Replace the `<p>` tag with:

```astro
{templateList.length === 0 ? (
    <div class="text-center py-10">
        <p class="text-4xl mb-3">📋</p>
        <p class="font-semibold text-brand-ink mb-1">
            {lang === "es" ? "Ninguna tarea todavía" : "No tasks yet"}
        </p>
        <p class="text-sm text-brand-ink-soft mb-4">
            {lang === "es" ? "Crea la primera para empezar" : "Create the first one to get started"}
        </p>
        <button
            id="open-create-template"
            class="inline-block bg-brand-sky text-white font-semibold px-5 py-2 rounded-xl hover:bg-brand-sky-deep transition-colors"
        >
            {lang === "es" ? "+ Crear tarea" : "+ Create task"}
        </button>
    </div>
) : (
```

Then in the existing JavaScript section, wire the button to open the create template modal. Find `document.getElementById("btn-create-template")` (or whatever the existing create button ID is) and add after it:

```javascript
document.getElementById("open-create-template")?.addEventListener("click", () => {
    document.getElementById("btn-create-template")?.click();
});
```

- [ ] **Step 2: Update rewards page empty state**

In `frontend/src/pages/rewards.astro`, find the block around line 145 where `rewards.length === 0` renders `(t(lang, "rewards_empty_title"))`. Replace that empty state section with:

```astro
{rewards.length === 0 ? (
    <div class="text-center py-10">
        <p class="text-4xl mb-3">🏆</p>
        <p class="font-semibold text-brand-ink mb-1">
            {lang === "es" ? "Ninguna recompensa todavía" : "No rewards yet"}
        </p>
        <p class="text-sm text-brand-ink-soft mb-4">
            {lang === "es" ? "Crea la primera para motivar a tus hijos" : "Create the first one to motivate your kids"}
        </p>
        <button
            id="open-create-reward"
            class="inline-block bg-brand-coral text-white font-semibold px-5 py-2 rounded-xl hover:bg-brand-coral-deep transition-colors"
        >
            {lang === "es" ? "+ Crear recompensa" : "+ Create reward"}
        </button>
    </div>
) : (
```

Wire to the existing create button (find the ID of the + Create reward button in the page and add):

```javascript
document.getElementById("open-create-reward")?.addEventListener("click", () => {
    document.getElementById("btn-add-reward")?.click();
});
```

- [ ] **Step 3: Verify in browser**

With a fresh family (no templates or rewards), visit:
- `http://localhost:3003/parent/tasks` — confirm the 📋 empty state with CTA button appears and clicking it opens the create form
- `http://localhost:3003/rewards` — confirm the 🏆 empty state with CTA button appears and clicking it opens the create form

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/parent/tasks.astro frontend/src/pages/rewards.astro
git commit -m "feat(onboarding): enhanced empty states with CTA on tasks + rewards pages"
```

---

## Task 9: Full Test Suite Verification

- [ ] **Step 1: Run full backend test suite**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ --no-cov -q 2>&1 | tail -10
```

Expected: same pass count as before this feature (922+ passed), 0 new failures.

- [ ] **Step 2: Run onboarding tests specifically**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_onboarding.py -v --no-cov
```

Expected: 13 passed, 0 failed.

- [ ] **Step 3: Final commit if clean**

No code changes — if all green, the feature is complete. Proceed to deploy.
