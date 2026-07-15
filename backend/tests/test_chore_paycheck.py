"""Chore paycheck — chore-proportional weekly allowance on the Family Bank.

Covers the payout math, what counts as done-&-approved, the parent release
(idempotent), and that the payday sweep does NOT auto-pay proportional mode.
"""
from datetime import date, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.family import Family
from app.models.kid_bank import KidBankAccount
from app.models.task_assignment import (
    ApprovalStatus,
    AssignmentStatus,
    TaskAssignment,
)
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.user import APPROVAL_APPROVED, User, UserRole
from app.services.bank_service import BankService

WEEK = date(2026, 7, 13)  # a Monday


async def _family(db):
    fam = Family(name="Fam", timezone="UTC")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


async def _user(db, fam, role=UserRole.TEEN):
    u = User(
        email=f"u{uuid4().hex[:10]}@t.com", name="T", role=role, family_id=fam.id,
        email_verified=True, cash_cents=0, points=0,
        approval_status=APPROVAL_APPROVED, is_active=True, preferred_lang="es",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _config(db, kid, **kw):
    acct = await BankService.ensure_account(db, kid)
    for k, v in kw.items():
        setattr(acct, k, v)
    await db.commit()
    await db.refresh(acct)
    return acct


async def _chore(db, fam, parent, kid, points, status,
                 approval=ApprovalStatus.NONE, bonus=False, week=WEEK):
    t = TaskTemplate(
        title="C", points=points, effort_level=1, interval_days=1, is_bonus=bonus,
        assignment_type=AssignmentType.AUTO, family_id=fam.id, created_by=parent.id,
    )
    db.add(t)
    await db.flush()
    a = TaskAssignment(
        template_id=t.id, assigned_to=kid.id, family_id=fam.id, status=status,
        approval_status=approval, assigned_date=week, week_of=week,
    )
    db.add(a)
    await db.commit()
    return a


# ── pure payout math ──────────────────────────────────────────────────────

def test_paycheck_cents_math():
    f = BankService._chore_paycheck_cents
    assert f(25000, 120, 120) == 25000          # 100% → full cap
    assert f(25000, 100, 120) == 20833          # 83% (floored)
    assert f(25000, 60, 120) == 12500           # 50%
    assert f(25000, 0, 120) == 0                # nothing done
    assert f(25000, 5, 0) == 0                  # nothing assigned → 0, no /0
    assert f(0, 120, 120) == 0                  # no cap set
    assert f(25000, 200, 120) == 25000          # never exceeds the cap


# ── what counts as done-&-approved ────────────────────────────────────────

@pytest.mark.asyncio
async def test_chore_points_counts_only_completed_and_approved(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED)                          # +20 (NONE ok)
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)  # +10
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.PENDING)   # awaiting → no
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.REJECTED)  # failed → no
    await _chore(db, fam, parent, kid, 10, AssignmentStatus.PENDING)                             # not done
    await _chore(db, fam, parent, kid, 40, AssignmentStatus.CANCELLED)                           # excluded both
    await _chore(db, fam, parent, kid, 99, AssignmentStatus.COMPLETED, bonus=True)               # gig → excluded

    done, assigned = await BankService._chore_points(db, fam.id, kid.id, WEEK)
    assert done == 30           # 20 + 10
    assert assigned == 60       # 20+10+10(pending appr)+10(rejected)+10(pending) — cancelled & gig out


# ── preview + release ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preview_projects_scaled_amount(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED)
    await _chore(db, fam, parent, kid, 20, AssignmentStatus.PENDING)
    p = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    assert p["assigned_points"] == 120 and p["done_points"] == 100
    assert p["pct"] == 83
    assert p["projected_cents"] == 20833
    assert p["already_released"] is False


@pytest.mark.asyncio
async def test_release_credits_and_is_idempotent(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 120, AssignmentStatus.COMPLETED)  # 100%

    r = await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert r["amount_cents"] == 25000
    u = await db.get(User, kid.id)
    assert u.cash_cents == 25000
    rows = (await db.execute(
        select(CashTransaction).where(
            CashTransaction.user_id == kid.id,
            CashTransaction.type == CashTransactionType.ALLOWANCE,
        )
    )).scalars().all()
    assert len(rows) == 1

    # second release for the same week → 409, no double pay
    with pytest.raises(Exception) as ei:
        await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert getattr(ei.value, "status_code", None) == 409
    u = await db.get(User, kid.id)
    assert u.cash_cents == 25000


@pytest.mark.asyncio
async def test_release_rejects_flat_mode(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="flat", allowance_cents=25000)
    with pytest.raises(Exception) as ei:
        await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert getattr(ei.value, "status_code", None) == 422


# ── sweep must NOT auto-pay proportional allowance ────────────────────────

@pytest.mark.asyncio
async def test_sweep_skips_proportional_allowance(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    await db.commit()
    u = await db.get(User, kid.id)
    assert u.cash_cents == 0  # released by the parent, not the sweep


@pytest.mark.asyncio
async def test_sweep_still_pays_flat_allowance(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="flat", allowance_cents=15000)
    await BankService._pay_one_kid(db, fam.id, kid.id)
    await db.commit()
    u = await db.get(User, kid.id)
    assert u.cash_cents == 15000
