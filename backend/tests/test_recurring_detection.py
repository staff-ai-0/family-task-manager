"""Tests for P2 recurring-charge detection.

TransactionService.detect_recurring_candidates scans a family's transaction
history for repeating (payee, ~amount, ~regular cadence) series and returns
candidates the user can promote to a recurring template. These tests verify a
planted monthly series is found, one-off / irregular spending is ignored,
payees with an existing active template are excluded, and results are
family-scoped.
"""

from datetime import date, timedelta

import pytest

from app.models.family import Family
from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetPayee,
    BudgetRecurringTransaction,
    BudgetTransaction,
)
from app.services.budget.transaction_service import TransactionService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _account(db, family_id, name="Card"):
    acct = BudgetAccount(family_id=family_id, name=name, type="checking", currency="MXN")
    db.add(acct)
    await db.flush()
    return acct


async def _payee(db, family_id, name):
    p = BudgetPayee(family_id=family_id, name=name)
    db.add(p)
    await db.flush()
    return p


async def _category(db, family_id, name):
    group = BudgetCategoryGroup(family_id=family_id, name=f"{name} Group")
    db.add(group)
    await db.flush()
    cat = BudgetCategory(family_id=family_id, group_id=group.id, name=name)
    db.add(cat)
    await db.flush()
    return cat


async def _txn(db, family_id, account_id, payee_id, amount, d, category_id=None):
    t = BudgetTransaction(
        family_id=family_id, account_id=account_id, payee_id=payee_id,
        amount=amount, date=d, category_id=category_id,
    )
    db.add(t)
    await db.flush()
    return t


def _monthly_dates(count):
    """`count` roughly-monthly dates ending near today (all within lookback)."""
    today = date.today()
    return [today - timedelta(days=30 * i) for i in range(count - 1, -1, -1)]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detects_planted_monthly_series(db_session, test_family):
    fid = test_family.id
    acct = await _account(db_session, fid)
    cat = await _category(db_session, fid, "Entretenimiento")
    netflix = await _payee(db_session, fid, "Netflix")

    for d in _monthly_dates(5):
        await _txn(db_session, fid, acct.id, netflix.id, -19900, d, category_id=cat.id)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(db_session, fid)
    assert len(candidates) == 1
    c = candidates[0]
    assert c["payee_id"] == netflix.id
    assert c["payee_name"] == "Netflix"
    assert c["cadence"] == "monthly"
    assert c["occurrences"] == 5
    assert c["amount_cents"] == -19900
    assert c["category_id"] == cat.id
    assert c["account_id"] == acct.id
    assert 26 <= c["avg_interval_days"] <= 35
    assert c["next_estimated_date"] > c["last_date"]


@pytest.mark.asyncio
async def test_ignores_one_off_and_below_threshold(db_session, test_family):
    fid = test_family.id
    acct = await _account(db_session, fid)
    store = await _payee(db_session, fid, "Random Store")
    gym = await _payee(db_session, fid, "Gym")

    # Single one-off charge → ignored.
    await _txn(db_session, fid, acct.id, store.id, -50000, date.today())
    # Only two monthly charges → below default min_occurrences=3.
    for d in _monthly_dates(2):
        await _txn(db_session, fid, acct.id, gym.id, -30000, d)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(db_session, fid)
    assert candidates == []


@pytest.mark.asyncio
async def test_ignores_irregular_series(db_session, test_family):
    fid = test_family.id
    acct = await _account(db_session, fid)
    shop = await _payee(db_session, fid, "Corner Shop")

    # Same amount, wildly irregular gaps (4 days, then ~5 months) → not a cadence.
    irregular = [date.today() - timedelta(days=150),
                 date.today() - timedelta(days=146),
                 date.today()]
    for d in irregular:
        await _txn(db_session, fid, acct.id, shop.id, -12000, d)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(db_session, fid)
    assert candidates == []


@pytest.mark.asyncio
async def test_ignores_varying_amounts(db_session, test_family):
    """Monthly cadence but each charge a very different amount → not one series."""
    fid = test_family.id
    acct = await _account(db_session, fid)
    market = await _payee(db_session, fid, "Mercado")

    amounts = [-10000, -55000, -120000]
    for d, amt in zip(_monthly_dates(3), amounts):
        await _txn(db_session, fid, acct.id, market.id, amt, d)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(db_session, fid)
    assert candidates == []


@pytest.mark.asyncio
async def test_excludes_payee_with_active_recurring_template(db_session, test_family):
    fid = test_family.id
    acct = await _account(db_session, fid)
    netflix = await _payee(db_session, fid, "Netflix")

    for d in _monthly_dates(5):
        await _txn(db_session, fid, acct.id, netflix.id, -19900, d)

    # An active recurring template already covers this payee.
    tmpl = BudgetRecurringTransaction(
        family_id=fid, account_id=acct.id, payee_id=netflix.id,
        name="Netflix", amount=-19900, recurrence_type="monthly_dayofmonth",
        recurrence_interval=1, start_date=date.today(), is_active=True,
    )
    db_session.add(tmpl)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(db_session, fid)
    assert candidates == []


@pytest.mark.asyncio
async def test_detection_is_family_scoped(db_session, test_family):
    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.flush()

    acct_b = await _account(db_session, other.id, "B Card")
    payee_b = await _payee(db_session, other.id, "Spotify")
    for d in _monthly_dates(5):
        await _txn(db_session, other.id, acct_b.id, payee_b.id, -11900, d)
    await db_session.commit()

    candidates = await TransactionService.detect_recurring_candidates(
        db_session, test_family.id
    )
    assert candidates == []
