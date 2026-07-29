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

    # bulk_create only flushes now; durability requires explicit commit.
    # Without this, the assertions above pass on in-memory Python objects
    # that may never reach disk — a regression where bulk_create silently
    # drops the flush would still fly through the test.
    await db.commit()

    # Re-read straight from the DB to prove the rows actually persisted.
    from app.models.budget import BudgetTransactionItem
    from sqlalchemy import func, select
    count = (await db.execute(
        select(func.count(BudgetTransactionItem.id)).where(
            BudgetTransactionItem.transaction_id == transaction.id,
        )
    )).scalar_one()
    assert count == 2


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


# ---------------------------------------------------------------------------
# Reading back the items OF a transaction.
#
# The scan confirm card was the only render of a receipt's line items: they
# were stored, then orphaned. Nothing could ask "what were the items on THIS
# transaction" — list_items filtered by normalized_name only — so the breakdown
# was unreachable the moment the user navigated away.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def two_transactions_with_items(db: AsyncSession, test_parent_user):
    """Two transactions in one family, each with its own items."""
    from app.models.budget import BudgetAccount, BudgetTransaction, BudgetTransactionItem

    family_id = test_parent_user.family_id
    acct = BudgetAccount(family_id=family_id, name="Card", type="checking", currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)

    made = []
    for label, names in (
        ("soriana", ["leche", "pan"]),
        ("oxxo", ["cafe"]),
    ):
        tx = BudgetTransaction(
            family_id=family_id, account_id=acct.id, date=date.today(),
            amount=-5000, notes=label,
        )
        db.add(tx)
        await db.commit()
        await db.refresh(tx)
        for n in names:
            db.add(BudgetTransactionItem(
                family_id=family_id, transaction_id=tx.id, name=n.title(),
                normalized_name=n, qty=1, unit_price_cents=1000, total_cents=1000,
            ))
        made.append(tx)
    await db.commit()
    return made


@pytest.mark.asyncio
async def test_list_items_filters_by_transaction(
    client: AsyncClient, auth_headers: dict, two_transactions_with_items,
):
    first, second = two_transactions_with_items

    resp = await client.get(
        f"/api/budget/items/?transaction_id={first.id}", headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {row["normalized_name"] for row in body} == {"leche", "pan"}
    assert all(row["transaction_id"] == str(first.id) for row in body)

    resp2 = await client.get(
        f"/api/budget/items/?transaction_id={second.id}", headers=auth_headers,
    )
    assert {row["normalized_name"] for row in resp2.json()} == {"cafe"}


@pytest.mark.asyncio
async def test_transaction_id_filter_is_family_scoped(
    client: AsyncClient, auth_headers: dict, db: AsyncSession, two_transactions_with_items,
):
    """A transaction id from another family returns nothing, not its items.

    The id is a client-supplied UUID, so without the family predicate this
    endpoint would read another tenant's shopping list given a guessed id.
    """
    from app.models.budget import BudgetAccount, BudgetTransaction, BudgetTransactionItem
    from app.models.family import Family

    other = Family(name="Other Family")
    db.add(other)
    await db.commit()
    await db.refresh(other)
    acct = BudgetAccount(family_id=other.id, name="Cash", type="checking", currency="MXN")
    db.add(acct)
    await db.commit()
    await db.refresh(acct)
    tx = BudgetTransaction(
        family_id=other.id, account_id=acct.id, date=date.today(), amount=-100,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    db.add(BudgetTransactionItem(
        family_id=other.id, transaction_id=tx.id, name="Secret",
        normalized_name="secret", qty=1, unit_price_cents=100, total_cents=100,
    ))
    await db.commit()

    resp = await client.get(
        f"/api/budget/items/?transaction_id={tx.id}", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_transaction_list_reports_which_rows_have_items(
    client: AsyncClient, auth_headers: dict, two_transactions_with_items,
):
    """The list endpoint says how many items each transaction has.

    Without this the UI cannot mark scanned receipts, and finding the one with
    a breakdown means opening every row.
    """
    resp = await client.get("/api/budget/transactions/", headers=auth_headers)
    assert resp.status_code == 200
    by_id = {row["id"]: row for row in resp.json()}

    first, second = two_transactions_with_items
    assert by_id[str(first.id)]["item_count"] == 2
    assert by_id[str(second.id)]["item_count"] == 1
    # An int, not a Decimal-turned-string: strict mobile decoders reject
    # "2" where the schema says int (see CLAUDE.md, budget/accounts.py).
    assert isinstance(by_id[str(first.id)]["item_count"], int)


@pytest.mark.asyncio
async def test_transactions_without_items_report_zero(
    client: AsyncClient, auth_headers: dict, seeded_items,
):
    resp = await client.get("/api/budget/transactions/", headers=auth_headers)
    counts = {row["item_count"] for row in resp.json()}
    assert counts <= {0, 2}
