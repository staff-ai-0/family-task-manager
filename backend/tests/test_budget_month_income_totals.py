"""Regression: the month view must count each income transaction exactly once.

`GET /api/budget/{year}/{month}` seeds totals.income from an account-level sum
of every positive on-budget transaction, which already INCLUDES transactions
categorized into an income group. A second `+=` of income-group activity used to
double-count them, inflating the dashboard's headline income card by up to 2x for
any family whose deposits get an income category — which is the norm, since every
family is seeded with an "Ingresos" group and both the AI categorizer and the
bank-email-matcher assign income categories automatically.
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.budget import (
    AccountCreate,
    CategoryCreate,
    CategoryGroupCreate,
    TransactionCreate,
)
from app.services.budget.account_service import AccountService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.transaction_service import TransactionService

MONTH = date(2026, 3, 1)
PAYCHECK_CENTS = 250000


async def _seed_income(db: AsyncSession, family_id, *, categorized: bool):
    """One on-budget account and one positive transaction for MONTH."""
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )
    category_id = None
    if categorized:
        group = await CategoryGroupService.create(
            db, family_id, CategoryGroupCreate(name="Ingresos", is_income=True)
        )
        category = await CategoryService.create(
            db, family_id, CategoryCreate(name="Salario", group_id=group.id)
        )
        category_id = category.id

    await TransactionService.create(
        db,
        family_id,
        TransactionCreate(
            account_id=account.id,
            date=date(2026, 3, 10),
            amount=PAYCHECK_CENTS,
            payee_name="Employer",
            category_id=category_id,
        ),
    )
    return account


@pytest.mark.asyncio
async def test_categorized_income_counted_once(
    client, db_session: AsyncSession, test_parent_user, auth_headers
):
    """A deposit assigned to an income category must not be counted twice."""
    await _seed_income(db_session, test_parent_user.family_id, categorized=True)

    resp = await client.get("/api/budget/month/2026/3", headers=auth_headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["totals"]["income"] == PAYCHECK_CENTS


@pytest.mark.asyncio
async def test_uncategorized_income_still_counted(
    client, db_session: AsyncSession, test_parent_user, auth_headers
):
    """The account-level figure must still include income with no category."""
    await _seed_income(db_session, test_parent_user.family_id, categorized=False)

    resp = await client.get("/api/budget/month/2026/3", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["totals"]["income"] == PAYCHECK_CENTS


@pytest.mark.asyncio
async def test_income_total_is_json_int_not_decimal_string(
    client, db_session: AsyncSession, test_parent_user, auth_headers
):
    """asyncpg returns Decimal for SUM(); strict mobile clients need a JSON int."""
    await _seed_income(db_session, test_parent_user.family_id, categorized=True)

    resp = await client.get("/api/budget/month/2026/3", headers=auth_headers)
    assert resp.status_code == 200

    raw = resp.json()["totals"]["income"]
    assert isinstance(raw, int), f"income serialized as {type(raw).__name__}: {raw!r}"
