# Economy Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add wishlist goal selection, progress tracking, and push nudge so kids name a reward they're working toward and get notified once they can afford it.

**Architecture:** New `user_reward_goals` table (one active goal per kid via partial unique index). `RewardGoalService` owns all goal logic. `check_nudge` wired into both point-award paths (gig approve + task auto-approve). `mark_achieved` wired into redemption. Dashboard and rewards page surface goal state in SSR.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, PostgreSQL 15 (partial unique index), Pydantic v2, Alembic, Astro 5, Tailwind CSS v4.

---

## File Map

**New files:**
- `backend/app/models/reward_goal.py` — `UserRewardGoal` ORM model
- `backend/app/schemas/reward_goal.py` — `GoalSet`, `GoalProgress` Pydantic schemas
- `backend/app/services/reward_goal_service.py` — `RewardGoalService` class
- `backend/migrations/versions/2026_06_09_add_user_reward_goals.py` — Alembic migration
- `backend/tests/test_reward_goals.py` — all goal tests (20 tests)

**Modified files:**
- `backend/app/models/__init__.py` — import `UserRewardGoal`
- `backend/app/models/notification.py` — add `GOAL_REACHED = "goal_reached"` to `NotificationType`
- `backend/app/services/__init__.py` — export `RewardGoalService`
- `backend/app/api/routes/rewards.py` — add 3 goal routes
- `backend/app/services/reward_service.py` — call `mark_achieved` in `redeem_reward`
- `backend/app/services/gig_claim_service.py` — call `check_nudge` in `approve` + `complete`
- `backend/app/services/task_assignment_service.py` — call `check_nudge` after auto-approve commit
- `frontend/src/pages/rewards.astro` — goal fetch, set/clear form actions, goal card UI
- `frontend/src/pages/dashboard.astro` — goal widget below points badge (3 states)

---

## Task 1: Alembic migration

**Files:**
- Create: `backend/migrations/versions/2026_06_09_add_user_reward_goals.py`

- [ ] **Step 1: Create migration file**

```python
"""user_reward_goals table

Revision ID: user_reward_goals
Revises: gig_tables
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'user_reward_goals'
down_revision = 'gig_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_reward_goals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reward_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('set_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('achieved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('nudge_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_user_reward_goals_user_id', 'user_reward_goals', ['user_id'])
    op.create_index('ix_user_reward_goals_family_id', 'user_reward_goals', ['family_id'])
    # One active goal per user, enforced at DB level
    op.execute(
        "CREATE UNIQUE INDEX ix_user_reward_goals_user_active "
        "ON user_reward_goals (user_id) WHERE achieved_at IS NULL"
    )


def downgrade() -> None:
    op.drop_table('user_reward_goals')
```

- [ ] **Step 2: Run migration against local dev DB**

```bash
podman exec family_app_backend alembic upgrade head
```

Expected output contains: `Running upgrade gig_tables -> user_reward_goals`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/versions/2026_06_09_add_user_reward_goals.py
git commit -m "feat(economy): add user_reward_goals migration"
```

---

## Task 2: SQLAlchemy model + register

**Files:**
- Create: `backend/app/models/reward_goal.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create model file**

```python
# backend/app/models/reward_goal.py
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class UserRewardGoal(Base):
    __tablename__ = "user_reward_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reward_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rewards.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    achieved_at = Column(DateTime(timezone=True), nullable=True)
    nudge_sent_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    reward = relationship("Reward")

    __table_args__ = (
        Index(
            "ix_user_reward_goals_user_active",
            "user_id",
            unique=True,
            postgresql_where=text("achieved_at IS NULL"),
        ),
    )
```

- [ ] **Step 2: Register in `backend/app/models/__init__.py`**

After the last import (`from app.models.gig import GigOffering, GigClaim, GigCategory, GigClaimStatus`), add:

```python
from app.models.reward_goal import UserRewardGoal
```

In `__all__`, add `"UserRewardGoal"` after `"GigClaimStatus"`.

- [ ] **Step 3: Verify import works**

```bash
podman exec family_app_backend python -c "from app.models import UserRewardGoal; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/reward_goal.py backend/app/models/__init__.py
git commit -m "feat(economy): UserRewardGoal model"
```

---

## Task 3: GOAL_REACHED notification type

**Files:**
- Modify: `backend/app/models/notification.py`

- [ ] **Step 1: Add constant to NotificationType class**

In `backend/app/models/notification.py`, add to the `NotificationType` class:

```python
GOAL_REACHED = "goal_reached"
```

Place it after `PET_NEEDS_ATTENTION = "pet_needs_attention"`.

- [ ] **Step 2: Verify**

```bash
podman exec family_app_backend python -c "from app.models.notification import NotificationType; print(NotificationType.GOAL_REACHED)"
```

Expected: `goal_reached`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/notification.py
git commit -m "feat(economy): GOAL_REACHED notification type"
```

---

## Task 4: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/reward_goal.py`

- [ ] **Step 1: Create schema file**

```python
# backend/app/schemas/reward_goal.py
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class GoalSet(BaseModel):
    reward_id: UUID


class GoalProgress(BaseModel):
    reward_id: UUID
    reward_title: str
    reward_icon: Optional[str] = None
    points_cost: int
    balance: int
    progress_pct: int   # 0–100
    pts_to_go: int
    affordable: bool
    set_at: datetime

    model_config = {"from_attributes": True}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/reward_goal.py
git commit -m "feat(economy): GoalSet + GoalProgress schemas"
```

---

## Task 5: RewardGoalService core (TDD)

**Files:**
- Create: `backend/app/services/reward_goal_service.py`
- Create: `backend/tests/test_reward_goals.py` (first batch of tests)

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_reward_goals.py
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func

from app.models.reward_goal import UserRewardGoal
from app.services.reward_goal_service import RewardGoalService
from app.core.exceptions import NotFoundException


# ── Core service tests ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_goal_creates_active_row(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(
        user_id=test_child_user.id,
        family_id=test_family.id,
        reward_id=test_reward.id,
        db=db_session,
    )
    goal = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    assert goal is not None
    assert goal.reward_id == test_reward.id
    assert goal.nudge_sent_at is None


@pytest.mark.asyncio
async def test_set_goal_replaces_existing(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="Second Reward",
        points_cost=200, category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)

    active = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
    ).scalars().all()
    assert len(active) == 1
    assert active[0].reward_id == reward2.id


@pytest.mark.asyncio
async def test_get_active_goal_returns_progress(db_session, test_family, test_child_user, test_reward):
    # test_child_user.points=100, test_reward.points_cost=100
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    progress = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)

    assert progress is not None
    assert progress.reward_id == test_reward.id
    assert progress.balance == 100
    assert progress.pts_to_go == 0
    assert progress.progress_pct == 100
    assert progress.affordable is True


@pytest.mark.asyncio
async def test_get_active_goal_returns_none_when_no_goal(db_session, test_family, test_child_user):
    result = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_clear_goal_removes_active_row(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.clear_goal(test_child_user.id, test_family.id, db_session)
    result = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_set_goal_rejects_inactive_reward(db_session, test_family, test_child_user):
    from app.models.reward import Reward, RewardCategory
    inactive = Reward(
        family_id=test_family.id, title="Inactive", points_cost=50,
        category=RewardCategory.TOYS, is_active=False,
    )
    db_session.add(inactive)
    await db_session.commit()
    await db_session.refresh(inactive)

    with pytest.raises(NotFoundException):
        await RewardGoalService.set_goal(
            test_child_user.id, test_family.id, inactive.id, db_session
        )
```

- [ ] **Step 2: Run — expect ImportError (service doesn't exist yet)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v 2>&1 | head -20
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'app.services.reward_goal_service'`

- [ ] **Step 3: Create service with core methods**

```python
# backend/app/services/reward_goal_service.py
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.reward import Reward
from app.models.reward_goal import UserRewardGoal
from app.models.user import User
from app.schemas.reward_goal import GoalProgress

log = logging.getLogger(__name__)


class RewardGoalService:

    @staticmethod
    async def set_goal(
        user_id: UUID,
        family_id: UUID,
        reward_id: UUID,
        db: AsyncSession,
    ) -> UserRewardGoal:
        reward = await db.scalar(
            select(Reward).where(
                Reward.id == reward_id,
                Reward.family_id == family_id,
                Reward.is_active.is_(True),
            )
        )
        if not reward:
            raise NotFoundException("Reward not found or not active")
        # Delete existing active goal, insert new one (delete+insert instead of
        # upsert — SQLAlchemy async lacks native partial-index conflict target)
        await db.execute(
            delete(UserRewardGoal).where(
                UserRewardGoal.user_id == user_id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
        goal = UserRewardGoal(user_id=user_id, family_id=family_id, reward_id=reward_id)
        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        return goal

    @staticmethod
    async def get_active_goal(
        user_id: UUID,
        family_id: UUID,
        db: AsyncSession,
    ) -> Optional[GoalProgress]:
        row = (
            await db.execute(
                select(UserRewardGoal, Reward)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).first()
        if not row:
            return None
        goal, reward = row
        user = await db.get(User, user_id)
        balance = user.points if user else 0
        pts_to_go = max(0, reward.points_cost - balance)
        progress_pct = (
            min(100, round(balance / reward.points_cost * 100))
            if reward.points_cost > 0 else 100
        )
        return GoalProgress(
            reward_id=reward.id,
            reward_title=reward.title,
            reward_icon=reward.icon,
            points_cost=reward.points_cost,
            balance=balance,
            progress_pct=progress_pct,
            pts_to_go=pts_to_go,
            affordable=balance >= reward.points_cost,
            set_at=goal.set_at,
        )

    @staticmethod
    async def clear_goal(user_id: UUID, family_id: UUID, db: AsyncSession) -> None:
        await db.execute(
            delete(UserRewardGoal).where(
                UserRewardGoal.user_id == user_id,
                UserRewardGoal.family_id == family_id,
                UserRewardGoal.achieved_at.is_(None),
            )
        )
        await db.commit()

    @staticmethod
    async def check_nudge(
        user_id: UUID,
        family_id: UUID,
        new_balance: int,
        db: AsyncSession,
    ) -> None:
        """Fire GOAL_REACHED notification+push exactly once when balance crosses goal threshold."""
        row = (
            await db.execute(
                select(UserRewardGoal, Reward)
                .join(Reward, UserRewardGoal.reward_id == Reward.id)
                .where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.family_id == family_id,
                    UserRewardGoal.achieved_at.is_(None),
                    UserRewardGoal.nudge_sent_at.is_(None),
                )
            )
        ).first()
        if not row:
            return
        goal, reward = row
        if new_balance < reward.points_cost:
            return
        try:
            from app.services.notification_service import NotificationService
            from app.models.notification import NotificationType as NT
            await NotificationService.create(
                db,
                family_id=family_id,
                user_id=user_id,
                type=NT.GOAL_REACHED,
                title="🎯 ¡Meta alcanzada! / Goal reached!",
                body=(
                    f"Tienes suficiente para {reward.title}. "
                    f"/ You have enough for {reward.title}."
                ),
                link="/rewards",
                push=True,
            )
        except Exception:
            log.warning("check_nudge: notification failed", exc_info=True)
            return
        goal.nudge_sent_at = datetime.now(timezone.utc)
        await db.commit()

    @staticmethod
    async def mark_achieved(
        user_id: UUID,
        reward_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Set achieved_at on the active goal matching this reward. Caller commits."""
        goal = (
            await db.execute(
                select(UserRewardGoal).where(
                    UserRewardGoal.user_id == user_id,
                    UserRewardGoal.reward_id == reward_id,
                    UserRewardGoal.achieved_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not goal:
            return
        goal.achieved_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: Run tests — expect 6 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/reward_goal_service.py backend/tests/test_reward_goals.py
git commit -m "feat(economy): RewardGoalService core + 6 tests"
```

---

## Task 6: check_nudge + mark_achieved tests

**Files:**
- Modify: `backend/tests/test_reward_goals.py`

- [ ] **Step 1: Append nudge + mark_achieved tests to `test_reward_goals.py`**

```python
# ── Nudge + mark_achieved tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_nudge_fires_notification(db_session, test_family, test_child_user, test_reward):
    # test_child_user.points=100, test_reward.points_cost=100 → affordable
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(
        user_id=test_child_user.id,
        family_id=test_family.id,
        new_balance=100,
        db=db_session,
    )
    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is not None
    assert notif.link == "/rewards"


@pytest.mark.asyncio
async def test_check_nudge_does_not_refire(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 150, db_session)

    from app.models.notification import Notification as Notif
    count = (
        await db_session.execute(
            select(func.count()).select_from(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar()
    assert count == 1


@pytest.mark.asyncio
async def test_check_nudge_does_not_fire_below_threshold(db_session, test_family, test_child_user, test_reward):
    # test_reward.points_cost=100; new_balance=50 → not affordable
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 50, db_session)

    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is None


@pytest.mark.asyncio
async def test_check_nudge_refires_after_new_goal(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="R2", points_cost=80,
        category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)
    # Switch goal → nudge_sent_at reset on new row
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)
    await RewardGoalService.check_nudge(test_child_user.id, test_family.id, 100, db_session)

    from app.models.notification import Notification as Notif
    count = (
        await db_session.execute(
            select(func.count()).select_from(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar()
    assert count == 2


@pytest.mark.asyncio
async def test_mark_achieved_sets_timestamp(db_session, test_family, test_child_user, test_reward):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()

    goal = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.reward_id == test_reward.id,
            )
        )
    ).scalar_one_or_none()
    assert goal is not None
    assert goal.achieved_at is not None


@pytest.mark.asyncio
async def test_mark_achieved_noop_when_no_goal(db_session, test_family, test_child_user, test_reward):
    # Must not raise
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)


@pytest.mark.asyncio
async def test_new_goal_settable_after_achieved(db_session, test_family, test_child_user, test_reward):
    from app.models.reward import Reward, RewardCategory
    reward2 = Reward(
        family_id=test_family.id, title="R3", points_cost=50,
        category=RewardCategory.TOYS, is_active=True,
    )
    db_session.add(reward2)
    await db_session.commit()
    await db_session.refresh(reward2)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await RewardGoalService.mark_achieved(test_child_user.id, test_reward.id, db_session)
    await db_session.commit()
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, reward2.id, db_session)

    progress = await RewardGoalService.get_active_goal(test_child_user.id, test_family.id, db_session)
    assert progress is not None
    assert progress.reward_id == reward2.id
```

- [ ] **Step 2: Run all tests — expect 13 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `13 passed`

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_reward_goals.py
git commit -m "test(economy): nudge + mark_achieved — 13 tests pass"
```

---

## Task 7: Routes GET/PUT/DELETE /api/rewards/goal (TDD)

**Files:**
- Modify: `backend/app/services/__init__.py`
- Modify: `backend/app/api/routes/rewards.py`
- Modify: `backend/tests/test_reward_goals.py`

- [ ] **Step 1: Export service in `backend/app/services/__init__.py`**

Add import:
```python
from app.services.reward_goal_service import RewardGoalService
```

Add `"RewardGoalService"` to `__all__`.

- [ ] **Step 2: Append route tests to `test_reward_goals.py`**

```python
# ── HTTP route tests ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_get_goal_returns_null_when_none(client, child_headers, test_child_user, test_family):
    res = await client.get("/api/rewards/goal", headers=child_headers)
    assert res.status_code == 200
    assert res.json() is None


@pytest.mark.asyncio
async def test_put_goal_sets_and_returns_progress(client, child_headers, test_child_user, test_family, test_reward):
    res = await client.put(
        "/api/rewards/goal",
        json={"reward_id": str(test_reward.id)},
        headers=child_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["reward_id"] == str(test_reward.id)
    assert "progress_pct" in data
    assert "pts_to_go" in data
    assert "affordable" in data


@pytest.mark.asyncio
async def test_delete_goal_clears(client, child_headers, test_child_user, test_family, test_reward, db_session):
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    res = await client.delete("/api/rewards/goal", headers=child_headers)
    assert res.status_code == 204
    check = await client.get("/api/rewards/goal", headers=child_headers)
    assert check.json() is None


@pytest.mark.asyncio
async def test_parent_put_goal_forbidden(client, parent_headers, test_family, test_reward):
    res = await client.put(
        "/api/rewards/goal",
        json={"reward_id": str(test_reward.id)},
        headers=parent_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_parent_get_goal_returns_null(client, parent_headers, test_family):
    res = await client.get("/api/rewards/goal", headers=parent_headers)
    assert res.status_code == 200
    assert res.json() is None
```

- [ ] **Step 3: Run route tests — expect failures (404)**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py::test_get_goal_returns_null_when_none tests/test_reward_goals.py::test_put_goal_sets_and_returns_progress -v 2>&1 | tail -8
```

Expected: `FAILED` — routes not yet registered

- [ ] **Step 4: Add routes to `backend/app/api/routes/rewards.py`**

Add these imports at the top of the file (after existing imports):

```python
from typing import Optional
from app.core.exceptions import ForbiddenException
from app.models.user import UserRole
from app.schemas.reward_goal import GoalSet, GoalProgress
from app.services.reward_goal_service import RewardGoalService
```

Add these three routes after the existing `delete_reward` route at the bottom:

```python
@router.get("/goal", response_model=Optional[GoalProgress])
async def get_reward_goal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current kid/teen's active goal with live progress. Returns null for parents."""
    if current_user.role == UserRole.PARENT:
        return None
    return await RewardGoalService.get_active_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )


@router.put("/goal", response_model=GoalProgress)
async def set_reward_goal(
    data: GoalSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set active reward goal. CHILD/TEEN only."""
    if current_user.role == UserRole.PARENT:
        raise ForbiddenException("Parents cannot set a reward goal")
    await RewardGoalService.set_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        reward_id=data.reward_id,
        db=db,
    )
    return await RewardGoalService.get_active_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )


@router.delete("/goal", status_code=status.HTTP_204_NO_CONTENT)
async def clear_reward_goal(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear active reward goal."""
    if current_user.role == UserRole.PARENT:
        raise ForbiddenException("Parents cannot clear a reward goal")
    await RewardGoalService.clear_goal(
        user_id=to_uuid_required(current_user.id),
        family_id=to_uuid_required(current_user.family_id),
        db=db,
    )
    return None
```

- [ ] **Step 5: Run all goal tests — expect 18 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `18 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/rewards.py backend/app/services/__init__.py backend/tests/test_reward_goals.py
git commit -m "feat(economy): GET/PUT/DELETE /api/rewards/goal routes"
```

---

## Task 8: Wire check_nudge in GigClaimService

**Files:**
- Modify: `backend/app/services/gig_claim_service.py`
- Modify: `backend/tests/test_reward_goals.py`

- [ ] **Step 1: Append integration test**

```python
# ── Integration: gig approve triggers nudge ───────────────────────────────────

@pytest.mark.asyncio
async def test_gig_approve_triggers_nudge(db_session, test_family, test_child_user, test_parent_user, test_reward):
    """Approving a gig that pushes balance to goal threshold fires GOAL_REACHED."""
    from app.models.gig import GigOffering, GigClaim, GigClaimStatus, GigCategory
    from app.services.gig_claim_service import GigClaimService

    test_child_user.points = 50  # 50 pts below test_reward.points_cost=100
    await db_session.commit()

    offering = GigOffering(
        family_id=test_family.id,
        created_by=test_parent_user.id,
        title="Wash car",
        points=50,
        difficulty=1,
        category=GigCategory.chores,
    )
    db_session.add(offering)
    await db_session.commit()
    await db_session.refresh(offering)

    claim = GigClaim(
        gig_id=offering.id,
        family_id=test_family.id,
        claimed_by=test_child_user.id,
        status=GigClaimStatus.COMPLETED,
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    await GigClaimService.approve(
        db=db_session,
        claim_id=claim.id,
        family_id=test_family.id,
        approver_id=test_parent_user.id,
        approved=True,
        notes=None,
    )

    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is not None
```

- [ ] **Step 2: Run — expect failure**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py::test_gig_approve_triggers_nudge -v 2>&1 | tail -5
```

Expected: `FAILED` (no GOAL_REACHED notification found)

- [ ] **Step 3: Wire check_nudge in `GigClaimService.approve`**

In `backend/app/services/gig_claim_service.py`, in the `approve` staticmethod, in the `if approved:` branch, immediately **before** `return claim` (after `await GigClaimService._notify_claimer_approved(...)`), add:

```python
            try:
                from app.services.reward_goal_service import RewardGoalService
                await RewardGoalService.check_nudge(
                    user_id=claim.claimed_by,
                    family_id=family_id,
                    new_balance=claimer.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after gig approve failed", exc_info=True
                )
```

- [ ] **Step 4: Wire check_nudge in `GigClaimService.complete` (auto-approve path)**

In `complete`, in the auto-approve branch (the `if claimer.gig_trust_streak >= threshold:` block), immediately **before** `return claim` (after `await GigClaimService._notify_claimer_approved(..., auto=True)`), add:

```python
            try:
                from app.services.reward_goal_service import RewardGoalService
                await RewardGoalService.check_nudge(
                    user_id=claim.claimed_by,
                    family_id=family_id,
                    new_balance=claimer.points,
                    db=db,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "check_nudge after gig auto-approve failed", exc_info=True
                )
```

- [ ] **Step 5: Run all goal tests — expect 19 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `19 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/gig_claim_service.py backend/tests/test_reward_goals.py
git commit -m "feat(economy): wire check_nudge in GigClaimService"
```

---

## Task 9: Wire check_nudge in TaskAssignmentService

**Files:**
- Modify: `backend/app/services/task_assignment_service.py`
- Modify: `backend/tests/test_reward_goals.py`

- [ ] **Step 1: Append integration test**

```python
# ── Integration: task auto-approve triggers nudge ─────────────────────────────

@pytest.mark.asyncio
async def test_task_auto_approve_triggers_nudge(
    db_session, test_family, test_child_user, test_parent_user, test_reward
):
    """Auto-approved bonus task crossing goal threshold fires GOAL_REACHED."""
    from app.models.task_template import TaskTemplate
    from app.models.task_assignment import TaskAssignment, AssignmentStatus, ApprovalStatus
    from app.services.task_assignment_service import TaskAssignmentService

    test_child_user.points = 0
    test_child_user.gig_trust_streak = 10  # above default threshold → auto-approve
    await db_session.commit()

    template = TaskTemplate(
        family_id=test_family.id,
        created_by=test_parent_user.id,
        title="Extra chore",
        is_bonus=True,
        award_points_per_completer=100,
        requires_photo_proof=False,
        blocks_rewards=False,
    )
    db_session.add(template)
    await db_session.commit()
    await db_session.refresh(template)

    assignment = TaskAssignment(
        family_id=test_family.id,
        template_id=template.id,
        assigned_to=test_child_user.id,
        status=AssignmentStatus.pending,
        approval_status=ApprovalStatus.none,
    )
    db_session.add(assignment)
    await db_session.commit()
    await db_session.refresh(assignment)

    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)

    await TaskAssignmentService.complete_assignment(
        db=db_session,
        assignment_id=assignment.id,
        user_id=test_child_user.id,
        family_id=test_family.id,
        proof_text="Done!",
        proof_image_url=None,
    )

    from app.models.notification import Notification as Notif
    notif = (
        await db_session.execute(
            select(Notif).where(
                Notif.user_id == test_child_user.id,
                Notif.type == "goal_reached",
            )
        )
    ).scalar_one_or_none()
    assert notif is not None
```

- [ ] **Step 2: Run — expect failure**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py::test_task_auto_approve_triggers_nudge -v 2>&1 | tail -5
```

Expected: `FAILED`

- [ ] **Step 3: Wire check_nudge in `complete_assignment`**

In `backend/app/services/task_assignment_service.py`, after `await db.commit()` and `await db.refresh(assignment)` (around line 712–713), immediately before the `# Fire-and-forget notifications` comment block, add:

```python
        if auto_approved:
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

- [ ] **Step 4: Run all goal tests — expect 20 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/task_assignment_service.py backend/tests/test_reward_goals.py
git commit -m "feat(economy): wire check_nudge in TaskAssignmentService"
```

---

## Task 10: Wire mark_achieved in RewardService.redeem_reward

**Files:**
- Modify: `backend/app/services/reward_service.py`
- Modify: `backend/tests/test_reward_goals.py`

- [ ] **Step 1: Append redemption test**

```python
# ── Integration: redeem marks goal achieved ───────────────────────────────────

@pytest.mark.asyncio
async def test_redeem_marks_goal_achieved(db_session, test_family, test_child_user, test_reward):
    """Redeeming the active goal reward sets achieved_at on the goal row."""
    await RewardGoalService.set_goal(test_child_user.id, test_family.id, test_reward.id, db_session)
    from app.services.reward_service import RewardService
    await RewardService.redeem_reward(
        db=db_session,
        reward_id=test_reward.id,
        user_id=test_child_user.id,
        family_id=test_family.id,
    )
    goal = (
        await db_session.execute(
            select(UserRewardGoal).where(
                UserRewardGoal.user_id == test_child_user.id,
                UserRewardGoal.reward_id == test_reward.id,
            )
        )
    ).scalar_one_or_none()
    assert goal is not None
    assert goal.achieved_at is not None
```

- [ ] **Step 2: Run — expect failure**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py::test_redeem_marks_goal_achieved -v 2>&1 | tail -5
```

Expected: `FAILED` (achieved_at is None)

- [ ] **Step 3: Add mark_achieved call in `reward_service.py`**

In `backend/app/services/reward_service.py`, in `redeem_reward`, replace the last two lines:

```python
        transaction = await PointsService.deduct_points_for_reward(
            db=db,
            user_id=user_id,
            reward_id=reward.id,
            points_cost=reward.points_cost,
        )

        return transaction
```

With:

```python
        transaction = await PointsService.deduct_points_for_reward(
            db=db,
            user_id=user_id,
            reward_id=reward.id,
            points_cost=reward.points_cost,
        )

        try:
            from app.services.reward_goal_service import RewardGoalService
            await RewardGoalService.mark_achieved(
                user_id=user_id, reward_id=reward.id, db=db
            )
            await db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).warning("mark_achieved failed", exc_info=True)

        return transaction
```

- [ ] **Step 4: Run all goal tests — expect 21 passing**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/test_reward_goals.py -v
```

Expected: `21 passed`

- [ ] **Step 5: Run full suite — verify no regressions**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q 2>&1 | tail -8
```

Expected: same baseline pass count (882+) with ≤5 pre-existing failures

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/reward_service.py backend/tests/test_reward_goals.py
git commit -m "feat(economy): wire mark_achieved in RewardService.redeem_reward"
```

---

## Task 11: Frontend — rewards page goal UI

**Files:**
- Modify: `frontend/src/pages/rewards.astro`

- [ ] **Step 1: Merge goal form actions into existing POST handler**

In `frontend/src/pages/rewards.astro`, replace the existing `if (Astro.request.method === "POST")` block (which currently handles only redemption) with:

```astro
if (Astro.request.method === "POST") {
    const data = await Astro.request.formData();
    const action = data.get("action") as string | null;
    const rewardId = data.get("reward_id") as string | null;

    if (action === "set_goal" && rewardId) {
        await apiFetch("/api/rewards/goal", {
            method: "PUT",
            token,
            body: JSON.stringify({ reward_id: rewardId }),
        });
    } else if (action === "clear_goal") {
        await apiFetch("/api/rewards/goal", { method: "DELETE", token });
    } else if (rewardId) {
        const { ok, error } = await apiFetch(
            `/api/rewards/${rewardId}/redeem`,
            { method: "POST", token },
        );
        if (ok) {
            Astro.cookies.set("flash", t(lang, "rewards_redeemed_flash"), {
                path: "/",
                maxAge: 5,
            });
        } else {
            Astro.cookies.set("flash_error", error || "Error", {
                path: "/",
                maxAge: 5,
            });
        }
    }
    return Astro.redirect("/rewards");
}
```

- [ ] **Step 2: Add activeGoal to the parallel data fetch**

Replace:
```astro
const [{ data: user }, { data: rewardsRaw }, { data: blockingRaw }] = await Promise.all([
    apiFetch<any>("/api/auth/me", { token }),
    apiFetch<any[]>("/api/rewards", { token }),
    apiFetch<any[]>("/api/task-assignments/blocking-rewards", { token }),
]);
```

With:
```astro
const [{ data: user }, { data: rewardsRaw }, { data: blockingRaw }, { data: activeGoalRaw }] = await Promise.all([
    apiFetch<any>("/api/auth/me", { token }),
    apiFetch<any[]>("/api/rewards", { token }),
    apiFetch<any[]>("/api/task-assignments/blocking-rewards", { token }),
    apiFetch<any>("/api/rewards/goal", { token }),
]);
```

After the existing `const isLocked = ...` line, add:
```astro
const activeGoal: any = activeGoalRaw ?? null;
const isKid = user?.role === "CHILD" || user?.role === "TEEN";
```

- [ ] **Step 3: Replace the reward card map with goal-aware markup**

Find the `rewards.map((reward: any) => {` block and replace the entire map return value with:

```astro
{rewards.map((reward: any) => {
    const isGoal = isKid && activeGoal?.reward_id === reward.id;
    const canAfford = user.points >= reward.points_cost;
    const canRedeem = canAfford && !isLocked;
    const pct = isGoal
        ? activeGoal.progress_pct
        : (reward.points_cost > 0
            ? Math.min(100, Math.round((user.points / reward.points_cost) * 100))
            : 100);
    const remaining = isGoal
        ? activeGoal.pts_to_go
        : Math.max(0, reward.points_cost - user.points);
    return (
        <div class={`bg-brand-cream rounded-2xl p-5 shadow-[var(--shadow-card)] border transition-all ${isGoal ? "border-brand-sky-deep ring-2 ring-brand-sky-deep/30" : "border-brand-ink/10"} ${(!canAfford && !isGoal) ? "opacity-60" : ""}`}>
            <div class="flex justify-between items-start mb-3">
                <div class="flex-1 pr-3">
                    {isGoal && (
                        <span class="inline-block mb-1 px-2 py-0.5 text-xs rounded-full bg-brand-sky-deep text-white font-semibold">
                            {lang === "es" ? "🎯 Tu Meta" : "🎯 Your Goal"}
                        </span>
                    )}
                    <h3 class="font-bold text-brand-ink text-lg mb-1">{reward.title}</h3>
                    {reward.description && (
                        <p class="text-brand-ink-soft text-sm line-clamp-2">{reward.description}</p>
                    )}
                    {reward.category && (
                        <span class="inline-block mt-2 px-2 py-0.5 text-xs rounded-full bg-brand-cream-deep text-brand-ink-soft font-medium">
                            {reward.category}
                        </span>
                    )}
                </div>
                <div class="flex flex-col items-center bg-brand-sun/20 rounded-xl px-3 py-2 flex-shrink-0">
                    <span class="text-brand-sun-deep text-xs font-semibold">{t(lang, "rewards_cost")}</span>
                    <span class="text-brand-sun-deep text-xl font-extrabold">{reward.points_cost}</span>
                    <span class="text-brand-sun-deep text-xs">{t(lang, "rewards_pts")}</span>
                </div>
            </div>
            <div class="mb-3">
                <div class="w-full bg-brand-cream-deep rounded-full h-2 overflow-hidden">
                    <div
                        class={`h-2 rounded-full transition-all duration-500 ${canAfford ? "bg-brand-mint" : (isGoal ? "bg-brand-sky-deep" : "bg-brand-sun-deep")}`}
                        style={`width: ${pct}%`}
                    ></div>
                </div>
                <p class="text-xs mt-1 font-medium text-brand-ink-soft">
                    {canAfford
                        ? (lang === "es" ? "✓ Listo para canjear" : "✓ Ready to redeem")
                        : (lang === "es" ? `Te faltan ${remaining} puntos` : `${remaining} points to go`)}
                </p>
            </div>
            <div class="flex gap-2">
                <form method="POST" class="flex-1">
                    <input type="hidden" name="reward_id" value={reward.id} />
                    <button
                        type="submit"
                        disabled={!canRedeem}
                        class={`w-full py-2.5 rounded-xl text-sm font-semibold transition-colors ${canRedeem ? "bg-brand-sun-deep hover:bg-brand-ink text-brand-ink shadow-[var(--shadow-card)] active:scale-95" : "bg-brand-cream-deep text-brand-ink-soft cursor-not-allowed"}`}
                    >
                        {lang === "es" ? "Canjear" : "Redeem"}
                    </button>
                </form>
                {isKid && !isGoal && (
                    <form method="POST">
                        <input type="hidden" name="action" value="set_goal" />
                        <input type="hidden" name="reward_id" value={reward.id} />
                        <button
                            type="submit"
                            class="px-3 py-2.5 rounded-xl text-sm font-semibold bg-brand-cream-deep text-brand-sky-deep border border-brand-sky-deep/30 hover:bg-brand-sky-deep/10 active:scale-95 transition-colors"
                            title={lang === "es" ? "Establecer como meta" : "Set as goal"}
                        >
                            {lang === "es" ? "🎯 Meta" : "🎯 Goal"}
                        </button>
                    </form>
                )}
                {isKid && isGoal && (
                    <form method="POST">
                        <input type="hidden" name="action" value="clear_goal" />
                        <button
                            type="submit"
                            class="px-3 py-2.5 rounded-xl text-sm font-medium text-brand-ink-soft hover:text-brand-ink active:scale-95 transition-colors"
                            title={lang === "es" ? "Quitar meta" : "Remove goal"}
                        >
                            ✕
                        </button>
                    </form>
                )}
            </div>
        </div>
    );
})}
```

- [ ] **Step 4: Check for Astro type errors**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check
```

Expected: `0 errors`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/rewards.astro
git commit -m "feat(economy): rewards page goal UI — ring/badge/set/clear"
```

---

## Task 12: Frontend — dashboard goal widget

**Files:**
- Modify: `frontend/src/pages/dashboard.astro`

- [ ] **Step 1: Add activeGoal fetch to SSR frontmatter**

In `frontend/src/pages/dashboard.astro`, after line 56 (`const toAutoApprove = Math.max(0, TRUST_THRESHOLD - trustStreak);`), add:

```astro
let activeGoal: any = null;
if (isKid) {
    const { data: goalData } = await apiFetch<any>("/api/rewards/goal", { token });
    activeGoal = goalData ?? null;
}
```

- [ ] **Step 2: Add goal widget inside the header**

In the `<header>` element, after the closing `})}` of the `{isKid && trustStreak > 0 && (...)}` block (around line 108), add:

```astro
{isKid && (
    <div class="mt-3">
        {activeGoal && !activeGoal.affordable && (
            <a
                href="/rewards"
                class="flex items-center gap-3 bg-white/15 backdrop-blur-sm rounded-xl px-4 py-2.5 border border-white/20 hover:bg-white/25 transition-colors"
            >
                <span class="text-xl">{activeGoal.reward_icon ?? "🎯"}</span>
                <div class="flex-1 min-w-0">
                    <p class="text-xs text-brand-cream font-semibold uppercase tracking-wider mb-0.5">
                        {lang === "es" ? "Tu Meta" : "Your Goal"}
                    </p>
                    <p class="text-sm font-bold text-white truncate">{activeGoal.reward_title}</p>
                    <div class="w-full bg-white/20 rounded-full h-1.5 mt-1 overflow-hidden">
                        <div
                            class="h-1.5 bg-brand-sun rounded-full transition-all duration-500"
                            style={`width: ${activeGoal.progress_pct}%`}
                        ></div>
                    </div>
                    <p class="text-xs text-brand-cream mt-0.5">
                        {lang === "es"
                            ? `${activeGoal.pts_to_go} pts para lograrlo`
                            : `${activeGoal.pts_to_go} pts to go`}
                    </p>
                </div>
            </a>
        )}
        {activeGoal && activeGoal.affordable && (
            <a
                href="/rewards"
                class="flex items-center gap-3 bg-brand-sun/30 backdrop-blur-sm rounded-xl px-4 py-2.5 border border-brand-sun/50 hover:bg-brand-sun/40 transition-colors"
            >
                <span class="text-2xl">🎉</span>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-bold text-white">
                        {lang === "es" ? "¡Meta alcanzada!" : "Goal reached!"}
                    </p>
                    <p class="text-xs text-brand-cream truncate">
                        {lang === "es"
                            ? `Puedes canjear ${activeGoal.reward_title} →`
                            : `Redeem ${activeGoal.reward_title} →`}
                    </p>
                </div>
            </a>
        )}
        {!activeGoal && (
            <a
                href="/rewards"
                class="block text-center text-xs text-brand-cream/70 hover:text-brand-cream py-1 transition-colors"
            >
                {lang === "es" ? "Elige una meta →" : "Set a goal →"}
            </a>
        )}
    </div>
)}
```

- [ ] **Step 3: Check for Astro type errors**

```bash
cd /Users/jc/dev-2026/AgentIA/family-task-manager/frontend && npm run check
```

Expected: `0 errors`

- [ ] **Step 4: Run full backend test suite one final time**

```bash
podman exec -e PYTHONPATH=/app family_app_backend pytest tests/ -q 2>&1 | tail -8
```

Expected: `21 new passes` in test_reward_goals, no new failures vs baseline

- [ ] **Step 5: Final commit**

```bash
git add frontend/src/pages/dashboard.astro
git commit -m "feat(economy): dashboard goal widget — 3 states (progress/affordable/empty)"
```

---

## Post-implementation checklist

- [ ] Run `./scripts/deploy-gcp.sh -y` to deploy to GCP prod (migration runs automatically)
- [ ] On prod VM, verify migration: `sudo docker compose exec -T postgres psql -U familyapp familyapp -c "\d user_reward_goals"`
- [ ] Log in as a kid, go to `/rewards`, set a goal — confirm ring + "Your Goal" badge appears
- [ ] Check dashboard — confirm goal widget shows with progress bar
- [ ] Earn enough points to hit goal threshold — confirm GOAL_REACHED notification appears in `/notifications`
- [ ] Redeem the goal reward — confirm `achieved_at` is set (no second nudge on re-earn)
