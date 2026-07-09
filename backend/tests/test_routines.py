"""Routines library tests.

Covers:
- routine CRUD + step ordering
- per-kid assignment visibility + family isolation
- full-routine completion awards POINTS + feeds the pet (never cash)
- partial completion awards nothing; the reward is idempotent
- parent-only authoring gate (API)
"""

import pytest
import pytest_asyncio

from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    ValidationException,
)
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.routine import Routine, RoutineStep
from app.services.pet_service import PetService
from app.services.routine_service import RoutineService


# ─── Fixtures: a second family + kids for isolation ──────────────────


@pytest_asyncio.fixture
async def other_family_2(db_session):
    from app.models.family import Family

    fam = Family(name="Other Family")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def other_child(db_session, other_family_2):
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole

    u = User(
        email="otherchild@test.com",
        password_hash=get_password_hash("password123"),
        name="Other Child",
        role=UserRole.CHILD,
        family_id=other_family_2.id,
        email_verified=True,
        points=0,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


async def _make_routine(db, family, *, assigned=None, points=15, steps=2):
    return await RoutineService.create_routine(
        db,
        family_id=family.id,
        created_by=None,
        name="Morning",
        name_es="Mañana",
        icon="🌅",
        time_of_day="morning",
        assigned_user_id=assigned.id if assigned else None,
        points_reward=points,
        steps=[
            {"label": f"Step {i}", "label_es": f"Paso {i}", "icon": "🪥"}
            for i in range(1, steps + 1)
        ],
    )


# ─── CRUD + ordering ─────────────────────────────────────────────────


class TestRoutineCRUD:
    async def test_create_with_steps(self, db_session, test_family):
        r = await _make_routine(db_session, test_family, steps=3)
        assert r.name == "Morning"
        assert r.name_es == "Mañana"
        assert r.points_reward == 15
        assert len(r.steps) == 3
        # steps come back ordered by sort_order
        orders = [s.sort_order for s in sorted(r.steps, key=lambda x: x.sort_order)]
        assert orders == [0, 1, 2]

    async def test_create_requires_name(self, db_session, test_family):
        with pytest.raises(ValidationException):
            await RoutineService.create_routine(
                db_session, family_id=test_family.id, created_by=None, name="  "
            )

    async def test_invalid_time_of_day_rejected(self, db_session, test_family):
        with pytest.raises(ValidationException):
            await RoutineService.create_routine(
                db_session,
                family_id=test_family.id,
                created_by=None,
                name="X",
                time_of_day="midnight",
            )

    async def test_add_and_reorder_steps(self, db_session, test_family):
        r = await _make_routine(db_session, test_family, steps=2)
        s3 = await RoutineService.add_step(
            db_session, test_family.id, r.id, label="Third", icon="👕"
        )
        # appended after existing max sort_order
        assert s3.sort_order == 2
        r = await RoutineService.get_routine_or_404(db_session, test_family.id, r.id)
        ordered = sorted(r.steps, key=lambda x: x.sort_order)
        # reverse the order
        reversed_ids = [s.id for s in reversed(ordered)]
        r = await RoutineService.reorder_steps(
            db_session, test_family.id, r.id, reversed_ids
        )
        new_order = [s.id for s in sorted(r.steps, key=lambda x: x.sort_order)]
        assert new_order == reversed_ids

    async def test_update_routine(self, db_session, test_family):
        r = await _make_routine(db_session, test_family)
        r = await RoutineService.update_routine(
            db_session,
            test_family.id,
            r.id,
            fields={"name": "Bedtime", "points_reward": 25, "time_of_day": "evening"},
        )
        assert r.name == "Bedtime"
        assert r.points_reward == 25
        assert r.time_of_day == "evening"

    async def test_delete_cascades_steps(self, db_session, test_family):
        from sqlalchemy import select

        r = await _make_routine(db_session, test_family, steps=2)
        rid = r.id
        await RoutineService.delete_routine(db_session, test_family.id, rid)
        with pytest.raises(NotFoundException):
            await RoutineService.get_routine_or_404(db_session, test_family.id, rid)
        steps = (
            await db_session.execute(
                select(RoutineStep).where(RoutineStep.routine_id == rid)
            )
        ).scalars().all()
        assert steps == []


# ─── Assignment + isolation ──────────────────────────────────────────


class TestAssignmentIsolation:
    async def test_per_kid_visibility(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        await _make_routine(db_session, test_family, assigned=test_child_user)
        child_list = await RoutineService.list_routines(
            db_session, test_family.id, for_user=test_child_user
        )
        teen_list = await RoutineService.list_routines(
            db_session, test_family.id, for_user=test_teen_user
        )
        assert len(child_list) == 1
        assert teen_list == []  # not assigned to the teen

    async def test_family_wide_visible_to_all(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        await _make_routine(db_session, test_family, assigned=None)
        child_list = await RoutineService.list_routines(
            db_session, test_family.id, for_user=test_child_user
        )
        teen_list = await RoutineService.list_routines(
            db_session, test_family.id, for_user=test_teen_user
        )
        assert len(child_list) == 1
        assert len(teen_list) == 1

    async def test_family_isolation_list(
        self, db_session, test_family, other_family_2
    ):
        await _make_routine(db_session, test_family)
        other = await RoutineService.list_routines(db_session, other_family_2.id)
        assert other == []

    async def test_family_isolation_get_404(
        self, db_session, test_family, other_family_2
    ):
        r = await _make_routine(db_session, test_family)
        with pytest.raises(NotFoundException):
            await RoutineService.get_routine_or_404(
                db_session, other_family_2.id, r.id
            )

    async def test_assign_cross_family_rejected(
        self, db_session, test_family, other_child
    ):
        with pytest.raises(ValidationException):
            await RoutineService.create_routine(
                db_session,
                family_id=test_family.id,
                created_by=None,
                name="X",
                assigned_user_id=other_child.id,
            )

    async def test_complete_wrong_kid_forbidden(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        r = await _make_routine(db_session, test_family, assigned=test_child_user)
        step_id = sorted(r.steps, key=lambda x: x.sort_order)[0].id
        with pytest.raises(ForbiddenException):
            await RoutineService.complete_step(
                db_session, test_teen_user, r.id, step_id
            )


# ─── Completion + reward (POINTS only, feeds pet) ────────────────────


async def _points(db, user_id):
    from app.services.base_service import get_user_by_id

    u = await get_user_by_id(db, user_id)
    return u.points, u.cash_cents


class TestCompletionReward:
    async def test_full_completion_awards_points_and_feeds_pet(
        self, db_session, test_family, test_child_user
    ):
        from sqlalchemy import select

        pet = await PetService.create_for_user(
            db_session, test_child_user.id, "Rex", "dog"
        )
        r = await _make_routine(
            db_session, test_family, assigned=test_child_user, points=15, steps=2
        )
        steps = sorted(r.steps, key=lambda x: x.sort_order)
        pts0, cash0 = await _points(db_session, test_child_user.id)

        # First step: no award yet.
        res1 = await RoutineService.complete_step(
            db_session, test_child_user, r.id, steps[0].id
        )
        assert res1["reward_granted"] is False
        assert res1["steps_done"] == 1
        assert res1["completed"] is False
        pts1, cash1 = await _points(db_session, test_child_user.id)
        assert pts1 == pts0
        assert cash1 == cash0

        # Second (last) step: award fires.
        res2 = await RoutineService.complete_step(
            db_session, test_child_user, r.id, steps[1].id
        )
        assert res2["reward_granted"] is True
        assert res2["completed"] is True
        assert res2["points_awarded"] == 15

        pts2, cash2 = await _points(db_session, test_child_user.id)
        assert pts2 == pts0 + 15  # POINTS credited
        assert cash2 == cash0     # cash NEVER touched (two-currency rule)

        # Pet fed (mandatory magnitude = 5 xp).
        await db_session.refresh(pet)
        assert pet.xp == 5

        # A BONUS point transaction was logged; no cash transaction exists.
        txns = (
            await db_session.execute(
                select(PointTransaction).where(
                    PointTransaction.user_id == test_child_user.id,
                    PointTransaction.type == TransactionType.BONUS,
                )
            )
        ).scalars().all()
        assert len(txns) == 1
        assert txns[0].points == 15

    async def test_no_cash_transaction_created(
        self, db_session, test_family, test_child_user
    ):
        from sqlalchemy import func, select
        from app.models.cash_transaction import CashTransaction

        r = await _make_routine(
            db_session, test_family, assigned=test_child_user, steps=1
        )
        step = r.steps[0]
        await RoutineService.complete_step(
            db_session, test_child_user, r.id, step.id
        )
        count = (
            await db_session.execute(
                select(func.count(CashTransaction.id)).where(
                    CashTransaction.user_id == test_child_user.id
                )
            )
        ).scalar()
        assert count == 0

    async def test_partial_completion_no_award(
        self, db_session, test_family, test_child_user
    ):
        r = await _make_routine(
            db_session, test_family, assigned=test_child_user, points=15, steps=3
        )
        steps = sorted(r.steps, key=lambda x: x.sort_order)
        pts0, _ = await _points(db_session, test_child_user.id)
        for s in steps[:2]:  # 2 of 3
            res = await RoutineService.complete_step(
                db_session, test_child_user, r.id, s.id
            )
            assert res["reward_granted"] is False
        pts1, _ = await _points(db_session, test_child_user.id)
        assert pts1 == pts0  # nothing awarded on partial completion

    async def test_reward_idempotent_on_retap(
        self, db_session, test_family, test_child_user
    ):
        r = await _make_routine(
            db_session, test_family, assigned=test_child_user, points=15, steps=2
        )
        steps = sorted(r.steps, key=lambda x: x.sort_order)
        pts0, _ = await _points(db_session, test_child_user.id)
        await RoutineService.complete_step(db_session, test_child_user, r.id, steps[0].id)
        await RoutineService.complete_step(db_session, test_child_user, r.id, steps[1].id)
        # Re-tap already-completed steps — must not double-award.
        again = await RoutineService.complete_step(
            db_session, test_child_user, r.id, steps[1].id
        )
        assert again["reward_granted"] is False
        pts1, _ = await _points(db_session, test_child_user.id)
        assert pts1 == pts0 + 15  # exactly one award

    async def test_single_step_awards_immediately(
        self, db_session, test_family, test_child_user
    ):
        r = await _make_routine(
            db_session, test_family, assigned=test_child_user, points=7, steps=1
        )
        res = await RoutineService.complete_step(
            db_session, test_child_user, r.id, r.steps[0].id
        )
        assert res["reward_granted"] is True
        assert res["points_awarded"] == 7

    async def test_family_wide_progress_is_per_kid(
        self, db_session, test_family, test_child_user, test_teen_user
    ):
        r = await _make_routine(db_session, test_family, assigned=None, steps=1)
        # Child completes; teen's board must still show pending.
        await RoutineService.complete_step(
            db_session, test_child_user, r.id, r.steps[0].id
        )
        teen_today = await RoutineService.today_for_user(db_session, test_teen_user)
        teen_routine = teen_today["routines"][0]
        assert teen_routine["steps_done"] == 0
        assert teen_routine["completed"] is False

    async def test_today_payload_shape(
        self, db_session, test_family, test_child_user
    ):
        await _make_routine(db_session, test_family, assigned=test_child_user, steps=2)
        payload = await RoutineService.today_for_user(db_session, test_child_user)
        assert payload["user_id"] == str(test_child_user.id)
        assert payload["color"].startswith("#")
        assert len(payload["routines"]) == 1
        assert payload["routines"][0]["total_steps"] == 2


# ─── API auth gate ───────────────────────────────────────────────────


class TestRoutineAPI:
    async def test_parent_creates_routine(self, client, auth_headers):
        resp = await client.post(
            "/api/routines/",
            headers=auth_headers,
            json={
                "name": "Morning",
                "name_es": "Mañana",
                "time_of_day": "morning",
                "points_reward": 10,
                "steps": [{"label": "Brush teeth", "icon": "🪥"}],
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "Morning"
        assert body["total_steps"] == 1

    async def test_child_cannot_create_routine(self, client, test_child_user):
        login = await client.post(
            "/api/auth/login",
            json={"email": "child@test.com", "password": "password123"},
        )
        token = login.json()["access_token"]
        resp = await client.post(
            "/api/routines/",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Sneaky", "steps": []},
        )
        assert resp.status_code == 403
