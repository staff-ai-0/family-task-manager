"""E2E tests for the budget recycle-bin HTTP contract.

Soft-delete → list → restore → permanently-delete, exercised through the
ROUTES (not the service layer) because that is where the recycle-bin has
actually broken in production twice: the list endpoint 500'd on raw ORM
objects, and restore/permanent-delete passed swapped arguments (PR #156).

Contract locked here:
- GET  /api/budget/recycle-bin/            → 200 {"data": [rows], "total": n}
  row = {"id", "type", "name", "deleted_at"}; ?item_type= filters.
- POST /api/budget/recycle-bin/<kind>/{id}/restore        → 200
- DELETE /api/budget/recycle-bin/<kind>/{id}/permanently  → 200
- DELETE /api/budget/recycle-bin/ (empty, >30d only)      → 200
- Parents only (require_parent_role) → child gets 403.
"""

import pytest
from datetime import date

from sqlalchemy import select

from app.models.budget import (
    BudgetAccount,
    BudgetCategory,
    BudgetCategoryGroup,
    BudgetTransaction,
)


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _setup(client, headers) -> dict:
    """Create group → category → account → transaction over the API."""
    r = await client.post(
        "/api/budget/categories/groups",
        json={"name": "Bin Group"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    group_id = r.json()["id"]

    r = await client.post(
        "/api/budget/categories/",
        json={"name": "Bin Category", "group_id": group_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    category_id = r.json()["id"]

    r = await client.post(
        "/api/budget/accounts/",
        json={"name": "Bin Account", "type": "checking"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    account_id = r.json()["id"]

    r = await client.post(
        "/api/budget/transactions/",
        json={
            "account_id": account_id,
            "date": date.today().isoformat(),
            "amount": -12345,
            "category_id": category_id,
            "payee_name": "Bin Payee",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    transaction_id = r.json()["id"]

    return {
        "group_id": group_id,
        "category_id": category_id,
        "account_id": account_id,
        "transaction_id": transaction_id,
    }


async def _bin_rows(client, headers, item_type: str | None = None) -> list[dict]:
    url = "/api/budget/recycle-bin/"
    if item_type:
        url += f"?item_type={item_type}"
    r = await client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["data"])
    return body["data"]


class TestRecycleBinWorkflow:
    @pytest.mark.asyncio
    async def test_soft_delete_lands_each_kind_in_bin(
        self, client, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        r = await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        assert r.status_code == 204, r.text
        r = await client.delete(
            f"/api/budget/accounts/{ids['account_id']}", headers=headers
        )
        assert r.status_code == 204, r.text
        r = await client.delete(
            f"/api/budget/categories/{ids['category_id']}", headers=headers
        )
        assert r.status_code == 204, r.text

        rows = await _bin_rows(client, headers)
        by_type = {(row["type"], row["id"]) for row in rows}
        assert ("transaction", ids["transaction_id"]) in by_type
        assert ("account", ids["account_id"]) in by_type
        assert ("category", ids["category_id"]) in by_type
        for row in rows:
            assert row["deleted_at"] is not None
            assert row["name"]

    @pytest.mark.asyncio
    async def test_filter_by_item_type(self, client, test_parent_user):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        await client.delete(
            f"/api/budget/accounts/{ids['account_id']}", headers=headers
        )

        rows = await _bin_rows(client, headers, item_type="transaction")
        assert rows, "filtered bin should not be empty"
        assert all(row["type"] == "transaction" for row in rows)
        assert any(row["id"] == ids["transaction_id"] for row in rows)

    @pytest.mark.asyncio
    async def test_restore_transaction(
        self, client, db_session, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        r = await client.post(
            f"/api/budget/recycle-bin/transactions/{ids['transaction_id']}/restore",
            headers=headers,
        )
        assert r.status_code == 200, r.text

        rows = await _bin_rows(client, headers)
        assert not any(row["id"] == ids["transaction_id"] for row in rows)

        tx = (await db_session.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.id == ids["transaction_id"]
            )
        )).scalar_one()
        assert tx.deleted_at is None

        # ...and it's back in the normal transaction list.
        r = await client.get("/api/budget/transactions/", headers=headers)
        assert r.status_code == 200, r.text
        listed = str(r.json())
        assert ids["transaction_id"] in listed

    @pytest.mark.asyncio
    async def test_restore_account_and_category(
        self, client, db_session, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/accounts/{ids['account_id']}", headers=headers
        )
        await client.delete(
            f"/api/budget/categories/{ids['category_id']}", headers=headers
        )

        r = await client.post(
            f"/api/budget/recycle-bin/accounts/{ids['account_id']}/restore",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        r = await client.post(
            f"/api/budget/recycle-bin/categories/{ids['category_id']}/restore",
            headers=headers,
        )
        assert r.status_code == 200, r.text

        acc = (await db_session.execute(
            select(BudgetAccount).where(BudgetAccount.id == ids["account_id"])
        )).scalar_one()
        assert acc.deleted_at is None
        cat = (await db_session.execute(
            select(BudgetCategory).where(
                BudgetCategory.id == ids["category_id"]
            )
        )).scalar_one()
        assert cat.deleted_at is None

    @pytest.mark.asyncio
    async def test_permanently_delete_transaction(
        self, client, db_session, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        r = await client.delete(
            f"/api/budget/recycle-bin/transactions/{ids['transaction_id']}/permanently",
            headers=headers,
        )
        assert r.status_code == 200, r.text

        rows = await _bin_rows(client, headers)
        assert not any(row["id"] == ids["transaction_id"] for row in rows)

        gone = (await db_session.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.id == ids["transaction_id"]
            )
        )).scalar_one_or_none()
        assert gone is None  # hard-deleted, not merely hidden

    @pytest.mark.asyncio
    async def test_group_delete_soft_cascades_to_categories(
        self, client, db_session, test_parent_user
    ):
        """Deleting a group soft-deletes its categories too — both restorable
        from the bin (the old hard CASCADE silently destroyed
        categorization)."""
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        r = await client.delete(
            f"/api/budget/categories/groups/{ids['group_id']}", headers=headers
        )
        assert r.status_code == 204, r.text

        rows = await _bin_rows(client, headers)
        by_type = {(row["type"], row["id"]) for row in rows}
        assert ("category_group", ids["group_id"]) in by_type
        assert ("category", ids["category_id"]) in by_type

        grp = (await db_session.execute(
            select(BudgetCategoryGroup).where(
                BudgetCategoryGroup.id == ids["group_id"]
            )
        )).scalar_one()
        assert grp.deleted_at is not None

    @pytest.mark.asyncio
    async def test_empty_recycle_bin_spares_recent_items(
        self, client, test_parent_user
    ):
        """Emptying the bin purges only items older than 30 days — a
        just-deleted item must survive."""
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        r = await client.delete("/api/budget/recycle-bin/", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        rows = await _bin_rows(client, headers)
        assert any(row["id"] == ids["transaction_id"] for row in rows)

    @pytest.mark.asyncio
    async def test_parent_only_access(
        self, client, test_parent_user, test_child_user
    ):
        headers = await _login(client, test_parent_user.email)
        r = await client.get("/api/budget/recycle-bin/", headers=headers)
        assert r.status_code == 200

        child_headers = await _login(client, test_child_user.email)
        r = await client.get("/api/budget/recycle-bin/", headers=child_headers)
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_soft_deleted_items_excluded_from_normal_queries(
        self, client, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        ids = await _setup(client, headers)

        await client.delete(
            f"/api/budget/transactions/{ids['transaction_id']}", headers=headers
        )
        r = await client.get("/api/budget/transactions/", headers=headers)
        assert r.status_code == 200, r.text
        assert ids["transaction_id"] not in str(r.json())
