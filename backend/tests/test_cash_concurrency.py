"""Concurrency guards for the two-currency money paths.

Regression tests for the code-review findings:
1. _get_user_locked must refresh (populate_existing) so a payout race can't
   overdraw / lose updates via a stale identity-map User.
2. complete_assignment must row-lock so a mandatory double-submit doesn't
   double-award points.
"""
import asyncio
from datetime import date

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import User, UserRole
from app.models.cash_transaction import CashTransaction
from app.models.point_transaction import PointTransaction, TransactionType
from app.models.task_assignment import TaskAssignment, AssignmentStatus
from app.services.cash_service import CashService
from app.services.task_assignment_service import TaskAssignmentService
from app.core.exceptions import ValidationException


@pytest.mark.asyncio
async def test_concurrent_payouts_cannot_overdraw(
    test_engine, db_session, test_family, test_parent_user, test_child_user
):
    """Two concurrent payouts that each fit alone but not together: exactly one
    succeeds, balance never goes negative, total paid <= initial balance."""
    test_child_user.cash_cents = 5000
    await db_session.commit()
    kid_id = test_child_user.id
    fam_id = test_family.id
    parent_id = test_parent_user.id

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _payout():
        async with maker() as s:
            # mirror the route: pre-load the user (verify_user_in_family) THEN lock
            await s.get(User, kid_id)
            return await CashService.record_payout(s, kid_id, fam_id, 3000, parent_id)

    results = await asyncio.gather(_payout(), _payout(), return_exceptions=True)
    ok = [r for r in results if isinstance(r, CashTransaction)]
    failed = [r for r in results if isinstance(r, Exception)]

    assert len(ok) == 1, f"expected exactly one payout to succeed, got {results}"
    assert len(failed) == 1 and isinstance(failed[0], ValidationException)

    await db_session.refresh(test_child_user)
    assert test_child_user.cash_cents == 2000  # 5000 - 3000, second rejected
    assert test_child_user.cash_cents >= 0


@pytest.mark.asyncio
async def test_concurrent_mandatory_complete_awards_points_once(
    test_engine, db_session, test_family, test_child_user, mandatory_template_factory
):
    """Double-submitting a mandatory completion must award points only once."""
    test_child_user.points = 0
    await db_session.commit()
    tmpl = await mandatory_template_factory(family=test_family, points=10)
    a = TaskAssignment(template_id=tmpl.id, family_id=test_family.id,
                       assigned_to=test_child_user.id, assigned_date=date.today(),
                       week_of=date.today(), status=AssignmentStatus.PENDING)
    db_session.add(a)
    await db_session.commit()
    await db_session.refresh(a)
    aid = a.id
    fam_id = test_family.id
    kid_id = test_child_user.id

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _complete():
        async with maker() as s:
            return await TaskAssignmentService.complete_assignment(s, aid, fam_id, kid_id)

    results = await asyncio.gather(_complete(), _complete(), return_exceptions=True)
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(failed) >= 1, f"expected one completion to be rejected, got {results}"

    txn_count = await db_session.scalar(
        select(func.count()).select_from(PointTransaction).where(
            PointTransaction.assignment_id == aid,
            PointTransaction.type == TransactionType.TASK_COMPLETED,
        )
    )
    assert txn_count == 1, f"double-award: {txn_count} point transactions"
    await db_session.refresh(test_child_user)
    assert test_child_user.points == 10


@pytest.mark.asyncio
async def test_concurrent_first_touch_bank_account_no_integrity_error(
    test_engine, db_session, test_family, test_child_user
):
    """Regression (Family Bank W1 review): the locked lazy-create path
    (_get_or_create_account_locked, used by award_gig_cash) and the non-locking
    BankService.ensure_account (used by GET /api/bank/me) can race on a brand-new
    kid — a FOR UPDATE select over a missing row takes no lock, so ensure_account
    can insert between the locked path's miss and its flush. Both must complete
    without a 500 on the UNIQUE(user_id) constraint, leaving exactly one account
    row with the jar invariant intact."""
    from app.models.kid_bank import KidBankAccount
    from app.models.user import User
    from app.services.bank_service import BankService

    test_child_user.cash_cents = 0
    await db_session.commit()
    kid_id = test_child_user.id
    fam_id = test_family.id

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _award():
        async with maker() as s:
            await s.get(User, kid_id)
            r = await CashService.award_gig_cash(s, kid_id, fam_id, None, 5000, "gig")
            await s.commit()
            return r

    async def _ensure():
        async with maker() as s:
            u = await s.get(User, kid_id)
            return await BankService.ensure_account(s, u)

    results = await asyncio.gather(_award(), _ensure(), return_exceptions=True)
    errs = [r for r in results if isinstance(r, Exception)]
    assert not errs, f"first-touch race raised: {errs}"

    rows = await db_session.scalar(
        select(func.count()).select_from(KidBankAccount).where(
            KidBankAccount.user_id == kid_id
        )
    )
    assert rows == 1, f"expected exactly one bank account row, got {rows}"

    acct = (await db_session.execute(
        select(KidBankAccount).where(KidBankAccount.user_id == kid_id)
    )).scalar_one()
    await db_session.refresh(test_child_user)
    assert (
        acct.spend_cents + acct.save_cents + acct.share_cents
        == test_child_user.cash_cents
    )
