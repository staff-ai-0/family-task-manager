"""Kid savings goal (P2) tests — CASH ledger / Save jar.

Covers: create (parent→active, kid→pending), approve, live progress against the
Save jar, reach + one-time celebration, the v1 "one active goal" rule, the
cash-ledger-only guarantee (no coupling to POINTS), parent gating (routes), and
family isolation.

Run: podman exec -e PYTHONPATH=/app family_app_backend \
     pytest tests/test_savings_goals.py -v --no-cov
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.family import Family
from app.models.kid_savings_goal import (
    GOAL_ACTIVE,
    GOAL_CANCELLED,
    GOAL_PENDING,
    KidSavingsGoal,
)
from app.models.notification import Notification
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.bank_service import BankService
from app.services.savings_goal_service import SavingsGoalService


# ── helpers ──────────────────────────────────────────────────────────────────


async def _mk_family(db):
    fam = Family(name="Fam", timezone="UTC")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


async def _mk_user(db, fam, role=UserRole.CHILD, cash=0, points=0):
    u = User(
        email=f"u{uuid4().hex[:10]}@t.com", name="Kid", role=role,
        family_id=fam.id, email_verified=True, cash_cents=cash, points=points,
        approval_status=APPROVAL_APPROVED, is_active=True, preferred_lang="es",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _set_save(db, kid, save_cents):
    """Put ``save_cents`` into the kid's Save jar, invariant-consistent."""
    acct = await BankService.ensure_account(db, kid)
    acct.spend_cents = 0
    acct.save_cents = save_cents
    acct.share_cents = 0
    kid.cash_cents = save_cents
    await db.commit()
    await db.refresh(acct)
    await db.refresh(kid)
    return acct


async def _goal_reached_count(db, user_id):
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.type == "goal_reached",
                )
            )
        ).scalar()
        or 0
    )


async def _login(client, email, pw="password123"):
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── create / approve ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parent_create_is_active(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    res = await SavingsGoalService.create_goal(
        db, parent, kid=kid, name="bici", target_cents=200000, emoji="🚲"
    )
    assert res["status"] == GOAL_ACTIVE
    assert res["pending_approval"] is False
    assert res["target_cents"] == 200000
    assert res["remaining_cents"] == 200000
    assert res["saved_cents"] == 0
    assert res["progress_pct"] == 0
    assert res["reached"] is False


@pytest.mark.asyncio
async def test_kid_propose_is_pending(db):
    fam = await _mk_family(db)
    await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    res = await SavingsGoalService.create_goal(
        db, kid, kid=kid, name="switch", target_cents=500000
    )
    assert res["status"] == GOAL_PENDING
    assert res["pending_approval"] is True


@pytest.mark.asyncio
async def test_approve_moves_pending_to_active(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    res = await SavingsGoalService.create_goal(
        db, kid, kid=kid, name="lego", target_cents=8000
    )
    approved = await SavingsGoalService.approve_goal(db, parent, res["id"])
    assert approved["status"] == GOAL_ACTIVE
    assert approved["pending_approval"] is False


# ── progress against the Save jar ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_progress_tracks_save_jar(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="bici", target_cents=10000)
    await _set_save(db, kid, 3000)
    prog = await SavingsGoalService.get_active(db, kid)
    assert prog["saved_cents"] == 3000
    assert prog["remaining_cents"] == 7000
    assert prog["progress_pct"] == 30
    assert prog["reached"] is False


@pytest.mark.asyncio
async def test_saved_cents_capped_at_target(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="bici", target_cents=10000)
    await _set_save(db, kid, 15000)  # over-saved
    prog = await SavingsGoalService.get_active(db, kid, notify=False)
    assert prog["saved_cents"] == 10000  # capped at target
    assert prog["save_balance_cents"] == 15000  # full jar still reported
    assert prog["remaining_cents"] == 0
    assert prog["progress_pct"] == 100
    assert prog["reached"] is True


# ── reach + one-time celebration ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reach_fires_celebration_once(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="bici", target_cents=10000)
    await _set_save(db, kid, 10000)

    prog = await SavingsGoalService.get_active(db, kid, notify=True)
    assert prog["reached"] is True
    assert prog["progress_pct"] == 100

    goal = (
        await db.execute(select(KidSavingsGoal).where(KidSavingsGoal.user_id == kid.id))
    ).scalar_one()
    assert goal.reached_at is not None

    first = await _goal_reached_count(db, kid.id)
    assert first == 1

    # Re-reading must NOT fire a second celebration (idempotent).
    await SavingsGoalService.get_active(db, kid, notify=True)
    assert await _goal_reached_count(db, kid.id) == first


@pytest.mark.asyncio
async def test_pending_goal_does_not_celebrate(db):
    fam = await _mk_family(db)
    await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    # Kid-proposed → pending; even if already funded, no celebration until active.
    await SavingsGoalService.create_goal(db, kid, kid=kid, name="bici", target_cents=5000)
    await _set_save(db, kid, 9000)
    prog = await SavingsGoalService.get_active(db, kid, notify=True)
    assert prog["reached"] is True  # balance is over target
    assert await _goal_reached_count(db, kid.id) == 0  # but pending → not celebrated
    goal = (
        await db.execute(select(KidSavingsGoal).where(KidSavingsGoal.user_id == kid.id))
    ).scalar_one()
    assert goal.reached_at is None


# ── cash-ledger only: NO points coupling ─────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_ignores_points_entirely(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="bici", target_cents=10000)

    # A pile of POINTS must not move the goal at all.
    kid.points = 999999
    await db.commit()
    prog = await SavingsGoalService.get_active(db, kid, notify=True)
    assert prog["saved_cents"] == 0
    assert prog["remaining_cents"] == 10000
    assert prog["reached"] is False
    assert await _goal_reached_count(db, kid.id) == 0

    # Only Save-jar CASH advances it.
    await _set_save(db, kid, 10000)
    prog2 = await SavingsGoalService.get_active(db, kid, notify=True)
    assert prog2["reached"] is True

    # Points were never touched by any of this.
    await db.refresh(kid)
    assert kid.points == 999999


# ── one active goal (v1) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_open_goal_rejected(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    await SavingsGoalService.create_goal(db, parent, kid=kid, name="a", target_cents=1000)
    with pytest.raises(HTTPException) as ei:
        await SavingsGoalService.create_goal(db, parent, kid=kid, name="b", target_cents=2000)
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_frees_the_slot(db):
    fam = await _mk_family(db)
    parent = await _mk_user(db, fam, role=UserRole.PARENT)
    kid = await _mk_user(db, fam)
    r1 = await SavingsGoalService.create_goal(db, parent, kid=kid, name="a", target_cents=1000)
    await SavingsGoalService.cancel_goal(db, parent, r1["id"])

    goal = (
        await db.execute(select(KidSavingsGoal).where(KidSavingsGoal.id == r1["id"]))
    ).scalar_one()
    assert goal.status == GOAL_CANCELLED

    # A new goal is now allowed.
    r2 = await SavingsGoalService.create_goal(db, parent, kid=kid, name="b", target_cents=2000)
    assert r2["status"] == GOAL_ACTIVE


@pytest.mark.asyncio
async def test_get_active_none_when_no_goal(db):
    fam = await _mk_family(db)
    kid = await _mk_user(db, fam)
    assert await SavingsGoalService.get_active(db, kid) is None


# ── isolation ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_family_approve_404(db):
    fam_a = await _mk_family(db)
    fam_b = await _mk_family(db)
    kid_a = await _mk_user(db, fam_a)
    await _mk_user(db, fam_a, role=UserRole.PARENT)
    parent_b = await _mk_user(db, fam_b, role=UserRole.PARENT)

    res = await SavingsGoalService.create_goal(db, kid_a, kid=kid_a, name="bici", target_cents=1000)
    with pytest.raises(HTTPException) as ei:
        await SavingsGoalService.approve_goal(db, parent_b, res["id"])
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_family_list_scoped(db):
    fam_a = await _mk_family(db)
    fam_b = await _mk_family(db)
    parent_a = await _mk_user(db, fam_a, role=UserRole.PARENT)
    kid_a = await _mk_user(db, fam_a)
    parent_b = await _mk_user(db, fam_b, role=UserRole.PARENT)
    kid_b = await _mk_user(db, fam_b)
    await SavingsGoalService.create_goal(db, parent_a, kid=kid_a, name="a", target_cents=1000)
    await SavingsGoalService.create_goal(db, parent_b, kid=kid_b, name="b", target_cents=1000)

    rows_a = await SavingsGoalService.get_family(db, parent_a)
    assert len(rows_a) == 1
    assert rows_a[0]["user_id"] == kid_a.id


# ── route-level parent gating ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_parent_requires_user_id(client, test_parent_user):
    h = await _login(client, "parent@test.com")
    r = await client.post("/api/bank/goals", json={"name": "x", "target_cents": 1000}, headers=h)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_route_kid_cannot_target_other_kid(client, test_child_user, test_teen_user):
    h = await _login(client, "child@test.com")
    r = await client.post(
        "/api/bank/goals",
        json={"name": "x", "target_cents": 1000, "user_id": str(test_teen_user.id)},
        headers=h,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_route_parent_target_must_be_kid(client, test_parent_user):
    h = await _login(client, "parent@test.com")
    r = await client.post(
        "/api/bank/goals",
        json={"name": "x", "target_cents": 1000, "user_id": str(test_parent_user.id)},
        headers=h,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_route_kid_self_goal_pending(client, test_child_user):
    h = await _login(client, "child@test.com")
    r = await client.post("/api/bank/goals", json={"name": "bici", "target_cents": 200000}, headers=h)
    assert r.status_code == 201
    assert r.json()["pending_approval"] is True
    assert r.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_route_parent_goal_for_kid_active(client, test_parent_user, test_child_user):
    h = await _login(client, "parent@test.com")
    r = await client.post(
        "/api/bank/goals",
        json={"name": "bici", "target_cents": 200000, "user_id": str(test_child_user.id)},
        headers=h,
    )
    assert r.status_code == 201
    assert r.json()["status"] == "active"


@pytest.mark.asyncio
async def test_route_my_goal_null_for_parent(client, test_parent_user):
    h = await _login(client, "parent@test.com")
    r = await client.get("/api/bank/goals/me", headers=h)
    assert r.status_code == 200
    assert r.json() is None
