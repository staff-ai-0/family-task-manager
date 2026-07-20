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


async def _gig_claim(db, family, kid, title, points=50):
    from app.models.gig import GigClaim, GigClaimStatus, GigOffering
    offering = GigOffering(family_id=family.id, title=title, points=points)
    db.add(offering)
    await db.flush()
    claim = GigClaim(
        gig_id=offering.id, family_id=family.id, claimed_by=kid.id,
        status=GigClaimStatus.APPROVED, points_awarded=points,
        approval_notes=f"notes for {title}",
    )
    from datetime import datetime, timezone
    claim.approved_at = datetime.now(timezone.utc)
    db.add(claim)
    await db.commit()
    await db.refresh(claim)
    return claim


@pytest.mark.asyncio
async def test_recent_gig_pills_all_time_when_never_paid(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family)
    claim = await _gig_claim(db, family, u, "Lavar el carro")
    await CashService.award_gig_cash(
        db, u.id, family.id, None, 5000, "gig", gig_claim_id=claim.id
    )
    await db.commit()

    pills = await CashService.recent_gig_pills(db, u.id)
    assert len(pills) == 1
    assert pills[0]["title"] == "Lavar el carro"
    assert pills[0]["amount_cents"] == 5000
    assert pills[0]["approval_notes"] == "notes for Lavar el carro"


@pytest.mark.asyncio
async def test_recent_gig_pills_only_since_last_payout(db, family):
    from app.services.cash_service import CashService
    u = await _kid(db, family)
    parent = await _kid(db, family)
    old_claim = await _gig_claim(db, family, u, "Old Gig")
    await CashService.award_gig_cash(
        db, u.id, family.id, None, 3000, "old", gig_claim_id=old_claim.id
    )
    await db.commit()
    await CashService.record_payout(db, u.id, family.id, 3000, parent.id)
    await db.commit()
    new_claim = await _gig_claim(db, family, u, "New Gig")
    await CashService.award_gig_cash(
        db, u.id, family.id, None, 2000, "new", gig_claim_id=new_claim.id
    )
    await db.commit()

    pills = await CashService.recent_gig_pills(db, u.id)
    assert [p["title"] for p in pills] == ["New Gig"]


@pytest.mark.asyncio
async def test_recent_gig_pills_groups_jar_split_rows(db, family):
    """One gig award can emit multiple CashTransaction rows (spend/save/share
    split) — must collapse to ONE pill per gig, amount summed."""
    from app.models.cash_transaction import CashTransactionType
    from app.services.cash_service import CashService
    from app.services.bank_service import BankService
    u = await _kid(db, family)
    acct = await BankService.ensure_account(db, u)
    acct.split_spend_pct, acct.split_save_pct, acct.split_share_pct = 50, 30, 20
    await db.commit()
    claim = await _gig_claim(db, family, u, "Split Gig")

    rows = CashService.credit_split_rows(
        db, u, acct, family.id, 10000, CashTransactionType.GIG_EARNED,
        entitled=True, gig_claim_id=claim.id, description="split",
    )
    await db.commit()
    assert len(rows) == 3  # sanity: the split really produced 3 rows

    pills = await CashService.recent_gig_pills(db, u.id)
    assert len(pills) == 1
    assert pills[0]["title"] == "Split Gig"
    assert pills[0]["amount_cents"] == 10000


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
