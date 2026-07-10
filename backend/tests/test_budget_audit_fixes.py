"""Budget audit fixes (2026-07-09 Playwright audit).

- Concurrent first-loads double-seeded the ENTIRE default category tree
  (prod: 24 groups / 88 categories — every group duplicated, including the
  visible double "INGRESOS"). The lazy seed's read-then-insert guard raced:
  two SSR fetches (month + groups) both saw 0 groups and both seeded.
- POST /api/budget/allocations/set gains mode="add": the Assign Funds modal
  ADDS to the current allocation instead of silently REPLACING it (assigning
  $100 used to wipe a $12,986 budget).
- Category/group DELETE is a soft delete (recycle-bin restorable) instead of
  a hard CASCADE delete.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models.budget import BudgetCategory, BudgetCategoryGroup


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestSeedRace:
    @pytest.mark.asyncio
    async def test_concurrent_seed_creates_single_tree(
        self, test_engine, db_session, test_family
    ):
        """Two seeds racing on separate sessions must produce ONE tree."""
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.services.budget.default_categories import (
            seed_default_categories,
        )

        maker = async_sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )

        async def seed_once():
            async with maker() as s:
                return await seed_default_categories(s, test_family.id)

        await asyncio.gather(seed_once(), seed_once())

        names = (await db_session.execute(
            select(BudgetCategoryGroup.name, func.count())
            .where(
                BudgetCategoryGroup.family_id == test_family.id,
                BudgetCategoryGroup.deleted_at.is_(None),
            )
            .group_by(BudgetCategoryGroup.name)
        )).all()
        dupes = [(n, c) for n, c in names if c > 1]
        assert not dupes, f"duplicated groups after concurrent seed: {dupes}"
        assert len(names) == 12  # full default tree exactly once


class TestAssignAddMode:
    @pytest.mark.asyncio
    async def test_set_mode_add_increments_existing_allocation(
        self, client, db_session, test_family, test_parent_user
    ):
        from app.services.budget.default_categories import (
            seed_default_categories,
        )
        await seed_default_categories(db_session, test_family.id)
        cat = (await db_session.execute(
            select(BudgetCategory).where(
                BudgetCategory.family_id == test_family.id
            ).limit(1)
        )).scalar_one()

        headers = await _login(client, test_parent_user.email)
        base = {"category_id": str(cat.id), "month": "2026-07-01"}

        r = await client.post("/api/budget/allocations/set", json={
            **base, "amount": 1298600,
        }, headers=headers)
        assert r.status_code == 200, r.text

        # mode=add → increments, never replaces
        r = await client.post("/api/budget/allocations/set", json={
            **base, "amount": 10000, "mode": "add",
        }, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["budgeted_amount"] == 1308600

        # default (no mode) keeps SET semantics
        r = await client.post("/api/budget/allocations/set", json={
            **base, "amount": 5000,
        }, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["budgeted_amount"] == 5000


class TestSoftDeleteCategories:
    @pytest.mark.asyncio
    async def test_category_delete_is_soft_and_restorable(
        self, client, db_session, test_family, test_parent_user
    ):
        from app.services.budget.default_categories import (
            seed_default_categories,
        )
        await seed_default_categories(db_session, test_family.id)
        cat = (await db_session.execute(
            select(BudgetCategory).where(
                BudgetCategory.family_id == test_family.id
            ).limit(1)
        )).scalar_one()

        headers = await _login(client, test_parent_user.email)
        r = await client.delete(
            f"/api/budget/categories/{cat.id}", headers=headers
        )
        assert r.status_code in (200, 204), r.text

        await db_session.refresh(cat)
        assert cat.deleted_at is not None  # soft, not gone

        # visible in the recycle bin
        r = await client.get("/api/budget/recycle-bin/", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        listed = str(body)
        assert str(cat.id) in listed
