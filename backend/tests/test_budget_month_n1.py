"""A4: the month budget view must not run an N+1 over categories.

`AllocationService.get_categories_available_amounts` is the batched replacement
for calling `get_category_available_amount` once per category. It must produce
identical numbers (correctness) using a small constant number of queries (perf).
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.budget.allocation_service import AllocationService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.transaction_service import TransactionService
from app.services.budget.account_service import AccountService
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryCreate,
    AccountCreate,
    TransactionCreate,
)

FEB = date(2026, 2, 1)
JAN = date(2026, 1, 1)


async def _seed(db: AsyncSession, family_id, n_extra: int = 0):
    """Seed a group with 2 base categories (one rollover, one not) plus n_extra
    more, each with prior-month + current-month allocations and transactions."""
    group = await CategoryGroupService.create(
        db, family_id, CategoryGroupCreate(name="Food", is_income=False)
    )
    account = await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )

    cats = []
    cat_roll = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="Groceries", group_id=group.id, rollover_enabled=True),
    )
    cat_noroll = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="Dining", group_id=group.id, rollover_enabled=False),
    )
    cats += [cat_roll, cat_noroll]
    for i in range(n_extra):
        cats.append(
            await CategoryService.create(
                db, family_id,
                CategoryCreate(name=f"Extra{i}", group_id=group.id, rollover_enabled=bool(i % 2)),
            )
        )

    for idx, c in enumerate(cats):
        # prior month (Jan): budget + spend
        await AllocationService.set_category_budget(db, family_id, c.id, JAN, 50000 + idx)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(account_id=account.id, date=date(2026, 1, 15),
                              amount=-(35000 + idx), category_id=c.id),
        )
        # current month (Feb): budget + spend
        await AllocationService.set_category_budget(db, family_id, c.id, FEB, 20000 + idx)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(account_id=account.id, date=date(2026, 2, 10),
                              amount=-(12000 + idx), category_id=c.id),
        )
    return cats


class TestMonthBudgetBatched:
    @pytest.mark.asyncio
    async def test_batched_equals_per_category(self, db: AsyncSession, family_id):
        """Batched output must match the per-category reference field-for-field."""
        cats = await _seed(db, family_id, n_extra=2)

        reference = {}
        for c in cats:
            reference[str(c.id)] = await AllocationService.get_category_available_amount(
                db, family_id, c.id, FEB
            )

        batched = await AllocationService.get_categories_available_amounts(
            db, family_id, FEB, cats
        )

        assert set(batched.keys()) == set(reference.keys())
        for cid, exp in reference.items():
            got = batched[cid]
            for field in ("budgeted", "activity", "previous_balance", "available", "rollover_enabled"):
                assert got[field] == exp[field], (
                    f"{field} mismatch for {cid}: batched={got[field]} ref={exp[field]}"
                )

    @pytest.mark.asyncio
    async def test_batched_query_count_is_constant(self, db: AsyncSession, family_id, monkeypatch):
        """The batched method must issue a small constant number of DB round-trips
        regardless of how many categories there are (no N+1)."""
        cats = await _seed(db, family_id, n_extra=2)  # 4 categories total

        calls = {"n": 0}
        original_execute = db.execute

        async def counting_execute(*args, **kwargs):
            calls["n"] += 1
            return await original_execute(*args, **kwargs)

        monkeypatch.setattr(db, "execute", counting_execute)
        await AllocationService.get_categories_available_amounts(db, family_id, FEB, cats)

        # 4 grouped aggregate queries — must not grow with the 4 categories.
        assert calls["n"] <= 5, (
            f"batched method issued {calls['n']} queries for {len(cats)} categories "
            f"— expected a small constant (~4), N+1 not eliminated"
        )

    @pytest.mark.asyncio
    async def test_month_endpoint_returns_correct_numbers(
        self, client, db: AsyncSession, test_parent_user, family_id
    ):
        """The GET month endpoint (now using the batched path) returns the same
        per-category figures as the reference calculation."""
        cats = await _seed(db, family_id, n_extra=0)
        ref = await AllocationService.get_category_available_amount(
            db, family_id, cats[0].id, FEB
        )

        login = await client.post(
            "/api/auth/login",
            json={"email": "parent@test.com", "password": "password123"},
        )
        token = login.json()["access_token"]
        r = await client.get(
            "/api/budget/month/2026/2", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200, r.text

        found = None
        for group in r.json()["category_groups"]:
            for c in group["categories"]:
                if c["id"] == str(cats[0].id):
                    found = c
        assert found is not None, "seeded category missing from month view"
        assert found["budgeted"] == ref["budgeted"]
        assert found["activity"] == ref["activity"]
        assert found["available"] == ref["available"]
        assert found["previous_balance"] == ref["previous_balance"]
