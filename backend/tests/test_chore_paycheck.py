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
async def test_chore_units_counts_only_completed_and_approved(db):
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

    done, assigned = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    # Units = points × pct (×100 for full credit).
    assert done == 3000         # (20 + 10) × 100
    assert assigned == 6000     # (20+10+10+10+10) × 100 — cancelled & gig out


@pytest.mark.asyncio
async def test_chore_units_partial_grade_scales_credit(db):
    """A 'partial' grade contributes partial_credit_pct of the task's points;
    a graded 'missed' (REJECTED) contributes 0. Grades never change assigned."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    full = await _chore(db, fam, parent, kid, 20, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    half = await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.APPROVED)
    missed = await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, ApprovalStatus.REJECTED)
    full.completion_grade = "full"
    half.completion_grade = "partial"
    half.partial_credit_pct = 50
    missed.completion_grade = "missed"
    await db.commit()

    done, assigned = await BankService._chore_units(db, fam.id, kid.id, WEEK)
    assert done == 2500         # 20×100 + 10×50 + 0
    assert assigned == 4000     # (20+10+10) × 100


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
async def test_release_records_week_of(db):
    """The ledger row must carry the paycheck week — feeds the payout
    history view (grouping past releases by week)."""
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 120, AssignmentStatus.COMPLETED)

    await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)

    row = (await db.execute(
        select(CashTransaction).where(
            CashTransaction.user_id == kid.id,
            CashTransaction.type == CashTransactionType.ALLOWANCE,
        )
    )).scalar_one()
    assert row.week_of == WEEK


@pytest.mark.asyncio
async def test_release_rejects_flat_mode(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="flat", allowance_cents=25000)
    with pytest.raises(Exception) as ei:
        await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert getattr(ei.value, "status_code", None) == 422


# ── payout history (past released weeks) ──────────────────────────────────

@pytest.mark.asyncio
async def test_history_empty_when_never_released(db):
    fam = await _family(db)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    result = await BankService.chore_paycheck_history(db, kid, fam.id)
    assert result["weeks"] == []
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_history_lists_past_weeks_newest_first_with_tasks(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    week1 = WEEK - timedelta(days=7)
    week2 = WEEK
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED, week=week1)
    await BankService.release_chore_paycheck(db, kid, fam.id, week1, entitled=True)
    await _chore(db, fam, parent, kid, 60, AssignmentStatus.COMPLETED, week=week2)
    await BankService.release_chore_paycheck(db, kid, fam.id, week2, entitled=True)

    result = await BankService.chore_paycheck_history(db, kid, fam.id)
    assert result["has_more"] is False
    assert [w["week_of"] for w in result["weeks"]] == [week2, week1]  # newest first
    assert result["weeks"][0]["amount_cents"] == 25000  # 100% of week2's 60 pts
    assert result["weeks"][1]["amount_cents"] == 25000  # 100% of week1's 100 pts
    # Task breakdown reuses the same per-task shape as payout-summary.
    assert [t["title"] for t in result["weeks"][1]["tasks"]] == ["C"]
    assert result["weeks"][1]["tasks"][0]["status"] == "credited"


@pytest.mark.asyncio
async def test_history_caps_and_reports_has_more(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=1000)

    for i in range(3):
        week = WEEK - timedelta(days=7 * i)
        await _chore(db, fam, parent, kid, 10, AssignmentStatus.COMPLETED, week=week)
        await BankService.release_chore_paycheck(db, kid, fam.id, week, entitled=True)

    result = await BankService.chore_paycheck_history(db, kid, fam.id, limit=2)
    assert len(result["weeks"]) == 2
    assert result["has_more"] is True


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


# ── parent adjustment on release ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_release_applies_adjustment(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 60, AssignmentStatus.COMPLETED)   # 100% of 60
    # base = 25000; +5000 bonus
    r = await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True, adjustment_cents=5000)
    assert r["amount_cents"] == 30000


@pytest.mark.asyncio
async def test_release_adjustment_floors_at_zero(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 60, AssignmentStatus.COMPLETED)
    r = await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True, adjustment_cents=-99999)
    assert r["amount_cents"] == 0


# ── notification on release + parent reminder ─────────────────────────────

@pytest.mark.asyncio
async def test_release_notifies_kid(db):
    from app.models.notification import Notification
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)
    await _chore(db, fam, parent, kid, 100, AssignmentStatus.COMPLETED)
    await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == kid.id)
    )).scalars().all()
    assert len(notes) >= 1


@pytest.mark.asyncio
async def test_reminder_notifies_parent_once(db):
    from app.models.notification import Notification
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_proportional", allowance_cents=25000)

    await BankService._remind_unreleased_paychecks(db, fam.id, WEEK)
    notes1 = (await db.execute(
        select(Notification).where(Notification.user_id == parent.id)
    )).scalars().all()
    assert len(notes1) == 1
    acct = (await db.execute(
        select(KidBankAccount).where(KidBankAccount.user_id == kid.id)
    )).scalar_one()
    assert acct.last_paycheck_reminder_week == WEEK

    # second run: idempotent — no new reminder
    await BankService._remind_unreleased_paychecks(db, fam.id, WEEK)
    notes2 = (await db.execute(
        select(Notification).where(Notification.user_id == parent.id)
    )).scalars().all()
    assert len(notes2) == 1
