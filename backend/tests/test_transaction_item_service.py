"""TransactionItemService — normalize names + CRUD + trend + HTTP endpoints."""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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


# ---------------------------------------------------------------------------
# HTTP endpoint tests — /api/budget/items
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_items(db: AsyncSession, test_parent_user):
    """A few BudgetTransactionItem rows under the authed user's (test_parent_user) family."""
    from app.models.budget import BudgetAccount, BudgetTransaction, BudgetTransactionItem
    family_id = test_parent_user.family_id
    # Create a minimal account + transaction to satisfy the FK
    acct = BudgetAccount(family_id=family_id, name="Cash", type="checking", currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)
    tx = BudgetTransaction(
        family_id=family_id, account_id=acct.id, date=date.today(), amount=-10000,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    now = datetime.now(timezone.utc)
    for i in range(2):
        db.add(BudgetTransactionItem(
            family_id=family_id,
            transaction_id=tx.id,
            name="Leche Alpura 1L",
            normalized_name="leche alpura",
            qty=1,
            unit_price_cents=3200 + i * 100,
            total_cents=3200 + i * 100,
            created_at=now - timedelta(days=i),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_list_items_filters_by_family(
    client: AsyncClient,
    auth_headers: dict,
    seeded_items,
):
    """GET /api/budget/items?normalized_name=leche+alpura returns seeded rows."""
    resp = await client.get(
        "/api/budget/items/?normalized_name=leche+alpura",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1


@pytest.mark.asyncio
async def test_trend_returns_null_when_below_sample(
    client: AsyncClient,
    auth_headers: dict,
    monkeypatch,
):
    """GET /api/budget/items/trend for unknown name returns 200 with null body.

    The endpoint is gated behind the Pro-only ``item_trends`` feature, so
    we patch the require_feature dependency to a no-op for this test.
    """
    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "app.api.routes.budget.items.require_feature", AsyncMock(),
    )
    resp = await client.get(
        "/api/budget/items/trend?normalized_name=nonexistent",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() is None
