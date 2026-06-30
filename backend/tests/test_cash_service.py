"""Tests for the cash currency: CashTransaction model + CashService."""

import pytest
from uuid import uuid4

from app.models.user import User, UserRole


# ── Task 1: model ────────────────────────────────────────────────────────────

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
    from app.models.cash_transaction import CashTransaction, CashTransactionType
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


# ── Task 3: CashService ──────────────────────────────────────────────────────

async def _kid(db, family, cents=0):
    u = User(email=f"k{uuid4().hex[:8]}@t.com", name="K", role=UserRole.CHILD,
             family_id=family.id, email_verified=True, cash_cents=cents)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_award_gig_cash_credits_balance(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family)
    await CashService.award_gig_cash(db, u.id, family.id, None, 5000, "gig")
    await db.commit()
    await db.refresh(u)
    assert u.cash_cents == 5000
    assert await CashService.get_balance(db, u.id) == 5000


@pytest.mark.asyncio
async def test_award_gig_cash_supports_negative_clawback(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family, cents=5000)
    await CashService.award_gig_cash(db, u.id, family.id, None, -2000, "resplit")
    await db.commit()
    await db.refresh(u)
    assert u.cash_cents == 3000


@pytest.mark.asyncio
async def test_record_payout_partial(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family, cents=12000)
    parent = await _kid(db, family)
    tx = await CashService.record_payout(db, u.id, family.id, 5000, parent.id)
    await db.refresh(u)
    assert u.cash_cents == 7000
    assert tx.amount_cents == -5000


@pytest.mark.asyncio
async def test_record_payout_rejects_overdraw(db, family):
    from app.services.cash_service import CashService
    from app.core.exceptions import ValidationException
    u = await _kid(db, family, cents=3000)
    parent = await _kid(db, family)
    with pytest.raises(ValidationException):
        await CashService.record_payout(db, u.id, family.id, 9999, parent.id)


@pytest.mark.asyncio
async def test_summary_math(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family)
    parent = await _kid(db, family)
    await CashService.award_gig_cash(db, u.id, family.id, None, 10000, "g")
    await db.commit()
    await CashService.record_payout(db, u.id, family.id, 4000, parent.id)
    s = await CashService.get_summary(db, u.id)
    assert s["current_balance"] == 6000
    assert s["total_earned"] == 10000
    assert s["total_paid"] == 4000
