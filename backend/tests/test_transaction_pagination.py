"""list_by_category must respect limit/offset — it was unbounded (audit M22)."""
from datetime import date
from uuid import uuid4

import pytest

from app.models.family import Family
from app.models.budget import (
    BudgetCategoryGroup,
    BudgetCategory,
    BudgetAccount,
    BudgetTransaction,
)
from app.services.budget.transaction_service import TransactionService


async def _setup(db):
    family = Family(id=uuid4(), name="F")
    db.add(family)
    await db.flush()
    group = BudgetCategoryGroup(id=uuid4(), family_id=family.id, name="G", is_income=False)
    db.add(group)
    await db.flush()
    cat = BudgetCategory(id=uuid4(), family_id=family.id, group_id=group.id, name="C")
    db.add(cat)
    await db.flush()
    acct = BudgetAccount(
        id=uuid4(), family_id=family.id, name="A", type="checking", starting_balance=0
    )
    db.add(acct)
    await db.flush()
    for i in range(5):
        db.add(
            BudgetTransaction(
                id=uuid4(), family_id=family.id, account_id=acct.id,
                category_id=cat.id, date=date(2026, 6, 1 + i), amount=-100,
            )
        )
    await db.commit()
    return family, cat


@pytest.mark.asyncio
async def test_list_by_category_respects_limit(db_session):
    family, cat = await _setup(db_session)
    page = await TransactionService.list_by_category(
        db_session, cat.id, family.id, limit=2
    )
    assert len(page) == 2


@pytest.mark.asyncio
async def test_list_by_category_default_unbounded_and_offset(db_session):
    family, cat = await _setup(db_session)
    all_txns = await TransactionService.list_by_category(db_session, cat.id, family.id)
    assert len(all_txns) == 5  # default (no limit) still returns everything
    page2 = await TransactionService.list_by_category(
        db_session, cat.id, family.id, limit=2, offset=2
    )
    assert len(page2) == 2
    # offset skips the first page
    assert {t.id for t in page2}.isdisjoint({t.id for t in all_txns[:2]})
