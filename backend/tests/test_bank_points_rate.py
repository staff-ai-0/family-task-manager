"""points_rate allowance mode — weekly piece-rate paycheck: grade-scaled chore
points × the family's point_value_cents, released by the parent like the other
chore paycheck modes. Released points are DEDUCTED from the kid's points
balance (they were pending cash), floored at the available balance.

Reuses helpers from ``test_chore_paycheck.py`` (``_family``, ``_user``,
``_config``, ``_chore``, fixed ``WEEK`` Monday).
"""
import pytest
from sqlalchemy import select

from app.models.point_transaction import PointTransaction
from app.models.task_assignment import ApprovalStatus, AssignmentStatus
from app.models.user import User, UserRole
from app.services.bank_service import ALLOWANCE_MODES, BankService
from tests.test_chore_paycheck import WEEK, _chore, _config, _family, _user


# ── pure payout math ──────────────────────────────────────────────────────


def test_points_rate_math():
    f = BankService._points_rate_cents
    assert f(3000, 100) == 3000      # 30 pts × $1.00 = $30.00
    assert f(3000, 250) == 7500      # 30 pts × $2.50 = $75.00
    assert f(2550, 100) == 2550      # 25.5 pts (partial) × $1.00 → floor to cents
    assert f(0, 100) == 0
    assert f(3000, 0) == 0


def test_points_rate_is_a_registered_mode():
    assert "points_rate" in ALLOWANCE_MODES


# ── preview ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_projects_points_times_family_rate(db):
    fam = await _family(db)
    fam.point_value_cents = 250  # 1 pt = $2.50
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)
    await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.PENDING)
    await db.commit()

    p = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    assert p["mode"] == "points_rate"
    assert p["done_points"] == 20 and p["assigned_points"] == 30
    assert p["projected_cents"] == 5000  # 20 pts × 250¢


# ── release: credits cash, deducts points ─────────────────────────────────


@pytest.mark.asyncio
async def test_release_credits_cash_and_deducts_points(db):
    fam = await _family(db)  # default rate 100 = 1pt/$1
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    kid.points = 50  # earned this + prior weeks
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)
    await _chore(db, fam, parent, kid, 30, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    await db.commit()

    r = await BankService.release_chore_paycheck(
        db, kid, fam.id, WEEK, entitled=True, released_by=parent.id
    )
    assert r["amount_cents"] == 3000
    assert r["points_converted"] == 30

    u = await db.get(User, kid.id)
    assert u.cash_cents == 3000
    assert u.points == 20  # 50 − 30 converted

    txn = (await db.execute(
        select(PointTransaction).where(PointTransaction.user_id == kid.id)
    )).scalars().all()
    assert len(txn) == 1
    assert txn[0].points == -30
    assert "convertidos" in (txn[0].description or "").lower()
    assert txn[0].created_by == parent.id

    # Idempotent per (kid, week).
    with pytest.raises(Exception) as ei:
        await BankService.release_chore_paycheck(
            db, kid, fam.id, WEEK, entitled=True, released_by=parent.id
        )
    assert getattr(ei.value, "status_code", None) == 409


@pytest.mark.asyncio
async def test_release_deduction_floors_at_available_balance(db):
    """Kid spent points on rewards mid-week: deduct what's left, pay in full."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    kid.points = 10  # already spent most of the 30 earned
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)
    await _chore(db, fam, parent, kid, 30, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    await db.commit()

    r = await BankService.release_chore_paycheck(
        db, kid, fam.id, WEEK, entitled=True, released_by=parent.id
    )
    assert r["amount_cents"] == 3000   # pay is per completed work, not balance
    assert r["points_converted"] == 10
    u = await db.get(User, kid.id)
    assert u.points == 0


@pytest.mark.asyncio
async def test_release_partial_grade_scales_pay(db):
    """20 pts full + 10 pts at 50% partial → 25 pts → $25.00 at default rate;
    deduction floors the half-point (25 pts, not 25.5)."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    kid.points = 100
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)
    await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    half = await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    half.completion_grade = "partial"
    half.partial_credit_pct = 50
    await db.commit()

    r = await BankService.release_chore_paycheck(
        db, kid, fam.id, WEEK, entitled=True, released_by=parent.id
    )
    assert r["amount_cents"] == 2500
    assert r["points_converted"] == 25
    u = await db.get(User, kid.id)
    assert u.points == 75


@pytest.mark.asyncio
async def test_points_rate_ignores_allowance_cap_and_zero_week_pays_nothing(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    kid.points = 40
    # cap set high — must be irrelevant; nothing completed this week.
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=99999)
    await _chore(db, fam, parent, kid, 30, AssignmentStatus.PENDING)
    await db.commit()

    r = await BankService.release_chore_paycheck(
        db, kid, fam.id, WEEK, entitled=True, released_by=parent.id
    )
    assert r["amount_cents"] == 0
    assert r["points_converted"] == 0
    u = await db.get(User, kid.id)
    assert u.points == 40 and u.cash_cents == 0


# ── payday sweep must not auto-pay points_rate ────────────────────────────


@pytest.mark.asyncio
async def test_payday_sweep_never_auto_pays_points_rate(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)
    await _chore(db, fam, parent, kid, 30, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    await db.commit()

    paid = await BankService._pay_one_kid(db, fam.id, kid.id)
    assert paid == 0
    u = await db.get(User, kid.id)
    assert u.cash_cents == 0


# ── reminder sweep covers points_rate kids (no cap required) ──────────────


@pytest.mark.asyncio
async def test_reminder_notifies_parent_for_points_rate_kid(db):
    from app.models.notification import Notification
    from app.models.kid_bank import KidBankAccount

    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="points_rate", allowance_cents=0)

    await BankService._remind_unreleased_paychecks(db, fam.id, WEEK)
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == parent.id)
    )).scalars().all()
    assert len(notes) == 1
    acct = (await db.execute(
        select(KidBankAccount).where(KidBankAccount.user_id == kid.id)
    )).scalar_one()
    assert acct.last_paycheck_reminder_week == WEEK


# ── family point value settings ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_point_value_cents_patch_parent_only(client, auth_headers, db_session):
    r = await client.patch(
        "/api/families/me", json={"point_value_cents": 250}, headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["point_value_cents"] == 250

    r = await client.patch(
        "/api/families/me", json={"point_value_cents": 0}, headers=auth_headers,
    )
    assert r.status_code == 422
