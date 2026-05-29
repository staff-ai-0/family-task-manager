"""TransactionItemService — normalize names + CRUD + trend."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.services.budget.transaction_item_service import (
    TransactionItemService, normalize_name,
)


def test_normalize_strips_accents_and_units():
    assert normalize_name("Leche Alpura 1L") == "leche alpura"
    assert normalize_name("Aguacate Hass kg") == "aguacate hass"
    assert normalize_name("PAN INTEGRAL 500g") == "pan integral"
    assert normalize_name("Café molido 250 g") == "cafe molido"
    assert normalize_name("Yogurt   griego  ") == "yogurt griego"
    assert normalize_name("3 PZA Tomate") == "tomate"


@pytest.mark.asyncio
async def test_bulk_create_persists_items(db, family, transaction):
    items = await TransactionItemService.bulk_create(
        db, family.id, transaction.id,
        items=[
            {"name": "Leche Alpura 1L", "qty": 2, "unit_price_cents": 3200,
             "total_cents": 6400, "brand": "Alpura"},
            {"name": "Pan integral", "total_cents": 4850},
        ],
    )
    assert len(items) == 2
    assert items[0].normalized_name == "leche alpura"
    assert items[1].normalized_name == "pan integral"


@pytest.mark.asyncio
async def test_get_trend_returns_none_below_sample_size(db, family):
    trend = await TransactionItemService.get_trend(
        db, family.id, normalized_name="leche alpura", window_days=90,
    )
    assert trend is None


@pytest.mark.asyncio
async def test_get_trend_computes_pct_change(db, family, transaction_factory):
    """Seed 4 items across recent dates; verify avg and pct_change."""
    from app.models.budget import BudgetTransactionItem
    now = datetime.now(timezone.utc)
    tx = await transaction_factory(family_id=family.id, date=date.today())
    for unit_price, days_ago in [(2500, 80), (2800, 60), (2900, 30), (3200, 1)]:
        db.add(BudgetTransactionItem(
            family_id=family.id, transaction_id=tx.id,
            name="leche", normalized_name="leche alpura",
            qty=1, unit_price_cents=unit_price, total_cents=unit_price,
            created_at=now - timedelta(days=days_ago),
        ))
    await db.commit()
    trend = await TransactionItemService.get_trend(
        db, family.id, normalized_name="leche alpura", window_days=90,
    )
    assert trend is not None
    assert trend.sample_size == 4
    assert trend.last_unit_cents == 3200
    # avg of first 3 priors = (2500+2800+2900)/3 = 2733
    assert trend.avg_unit_cents == 2733
    # pct_change = (3200 - 2733) / 2733 ≈ 0.171
    assert 0.16 < trend.pct_change < 0.18


@pytest.mark.asyncio
async def test_tenant_isolation_on_list(db, family, other_family, transaction):
    """Family A cannot read Family B's items."""
    from app.models.budget import BudgetTransactionItem
    db.add(BudgetTransactionItem(
        family_id=other_family.id, transaction_id=transaction.id,
        name="bread", normalized_name="bread", total_cents=1000,
    ))
    await db.commit()
    rows = await TransactionItemService.list_for_family(
        db, family.id, normalized_name="bread",
    )
    assert rows == []
