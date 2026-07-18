"""chore_gated allowance mode — an all-or-nothing weekly chore paycheck: pays
the full weekly cap iff 100% of a kid's obligatory (non-bonus) chore points
are completed-and-approved for the week, else $0.

Reuses the chore-proportional plumbing (``_chore_points``, ``chore_paycheck_
preview``, ``release_chore_paycheck``) from ``test_chore_paycheck.py`` — see
that file for the sibling ``chore_proportional`` mode and its helpers
(``_family``, ``_user``, ``_config``, ``_chore``, the fixed ``WEEK`` Monday
constant used to keep these tests clock-independent).
"""
import pytest
from sqlalchemy import select

from app.models.kid_bank import KidBankAccount
from app.models.task_assignment import ApprovalStatus, AssignmentStatus
from app.models.user import User, UserRole
from app.services.bank_service import ALLOWANCE_MODES, BankService
from tests.test_chore_paycheck import WEEK, _chore, _config, _family, _user


# ── pure payout math ──────────────────────────────────────────────────────


def test_chore_gated_pays_full_cap_at_100pct():
    assert BankService._chore_paycheck_gated(25000, 8, 8) == 25000


def test_chore_gated_pays_zero_below_100pct():
    assert BankService._chore_paycheck_gated(25000, 7, 8) == 0


def test_chore_gated_pays_zero_when_nothing_assigned():
    assert BankService._chore_paycheck_gated(25000, 0, 0) == 0


def test_chore_gated_pays_zero_for_zero_cap():
    assert BankService._chore_paycheck_gated(0, 8, 8) == 0


def test_chore_gated_is_a_registered_mode():
    assert "chore_gated" in ALLOWANCE_MODES


# ── integration: preview + release gate on 100% completion ────────────────


@pytest.mark.asyncio
async def test_gated_release_pays_only_at_full_completion(db):
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_gated", allowance_cents=25000)

    # Two obligatory (non-bonus) templates assigned for the week; neither done yet.
    a1 = await _chore(db, fam, parent, kid, 10, AssignmentStatus.PENDING)
    a2 = await _chore(db, fam, parent, kid, 10, AssignmentStatus.PENDING)

    # Complete + approve only the first → still short of 100% → $0 projected.
    a1.status = AssignmentStatus.COMPLETED
    a1.approval_status = ApprovalStatus.APPROVED
    await db.commit()
    preview = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    assert preview["projected_cents"] == 0

    # Complete + approve the second → 100% done → full cap projected.
    a2.status = AssignmentStatus.COMPLETED
    a2.approval_status = ApprovalStatus.APPROVED
    await db.commit()
    preview = await BankService.chore_paycheck_preview(db, kid, fam.id, week_of=WEEK)
    assert preview["projected_cents"] == 25000

    result = await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert result["amount_cents"] == 25000
    u = await db.get(User, kid.id)
    assert u.cash_cents == 25000

    # A second release for the same week must not double-pay.
    with pytest.raises(Exception) as ei:
        await BankService.release_chore_paycheck(db, kid, fam.id, WEEK, entitled=True)
    assert getattr(ei.value, "status_code", None) == 409
    u = await db.get(User, kid.id)
    assert u.cash_cents == 25000


# ── weekly parent-nudge sweep must also cover gated kids ───────────────────
#
# Contract: "chore_gated accepted anywhere chore_proportional is." The sweep
# (_remind_unreleased_paychecks) must nudge parents for an unreleased
# chore_gated paycheck too, not just chore_proportional — mirrors
# test_reminder_notifies_parent_once in test_chore_paycheck.py.


@pytest.mark.asyncio
async def test_reminder_notifies_parent_for_gated_kid(db):
    from app.models.notification import Notification
    fam = await _family(db)
    parent = await _user(db, fam, UserRole.PARENT)
    kid = await _user(db, fam)
    await _config(db, kid, allowance_mode="chore_gated", allowance_cents=25000)

    await BankService._remind_unreleased_paychecks(db, fam.id, WEEK)
    notes = (await db.execute(
        select(Notification).where(Notification.user_id == parent.id)
    )).scalars().all()
    assert len(notes) == 1
    acct = (await db.execute(
        select(KidBankAccount).where(KidBankAccount.user_id == kid.id)
    )).scalar_one()
    assert acct.last_paycheck_reminder_week == WEEK
