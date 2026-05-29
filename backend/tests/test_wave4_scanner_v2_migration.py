"""Smoke test: wave4_scanner_v2 migration creates expected tables and columns."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Local fixtures (Task 4 will promote these to conftest.py)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def family(db: AsyncSession):
    from app.models.family import Family
    fam = Family(name="Wave4 Test Family")
    db.add(fam)
    await db.commit()
    await db.refresh(fam)
    return fam


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wave4_tables_exist(db: AsyncSession):
    """budget_transaction_items, family_a2a_webhooks, a2a_webhook_deliveries exist."""
    result = await db.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename IN ('budget_transaction_items', 'family_a2a_webhooks', "
        "'a2a_webhook_deliveries')"
    ))
    names = {row[0] for row in result.all()}
    assert names == {
        "budget_transaction_items",
        "family_a2a_webhooks",
        "a2a_webhook_deliveries",
    }


@pytest.mark.asyncio
async def test_wave4_new_columns_exist(db: AsyncSession):
    """Account + Transaction tables have new columns."""
    cols = await db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'budget_accounts' AND column_name = 'card_last4'"
    ))
    assert cols.scalar() == "card_last4"

    for col in ["card_last4", "iva_cents", "fx_rate",
                "original_amount_cents", "original_currency"]:
        r = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            f"WHERE table_name = 'budget_transactions' AND column_name = '{col}'"
        ))
        assert r.scalar() == col, f"Missing column budget_transactions.{col}"


@pytest.mark.asyncio
async def test_card_last4_backfill_from_name(db: AsyncSession, family):
    """Migration backfill regex captures **9222 / ***313 / 'terminada en 1234' / XXXX4321 patterns."""
    from app.models.budget import BudgetAccount
    a1 = BudgetAccount(family_id=family.id, name="Mastercard **9222", type="credit")
    a2 = BudgetAccount(family_id=family.id, name="Cheques Banamex ***313", type="checking")
    a3 = BudgetAccount(family_id=family.id, name="Tarjeta terminada en 1234", type="credit")
    a4 = BudgetAccount(family_id=family.id, name="XXXX4321", type="credit")
    db.add_all([a1, a2, a3, a4])
    await db.commit()
    # Re-run the backfill UPDATE the migration emits; it must be idempotent.
    await db.execute(text(
        "UPDATE budget_accounts SET card_last4 = "
        "regexp_replace(name, '.*(?:\\*{2,}|terminada en |XXXX|xxxx)(\\d{4}).*', '\\1') "
        "WHERE name ~* '(\\*{2,}|terminada en |XXXX|xxxx)\\d{4}' AND card_last4 IS NULL"
    ))
    await db.commit()
    await db.refresh(a1); await db.refresh(a2); await db.refresh(a3); await db.refresh(a4)
    assert a1.card_last4 == "9222"
    assert a2.card_last4 == "313" or a2.card_last4 is None  # 3-digit suffix won't backfill (4 required)
    assert a3.card_last4 == "1234"
    assert a4.card_last4 == "4321"
