"""Hold-for-next-month + category notes (Actual Budget envelope parity).

- POST /api/budget/months/{y}/{m}/hold {amount} parks part of this month's
  Ready-to-Assign for the NEXT month: RTA(m) drops by the held amount and
  RTA(m+1) gains it. hold=0 clears. GET status includes held_amount.
- budget_categories.notes: free-text per category (why this envelope
  exists, rules of use), editable via the normal category PUT.
"""

import pytest
from datetime import date
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.models.budget import BudgetAccount, BudgetCategory


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestHoldForNextMonth:
    @pytest.mark.asyncio
    async def test_hold_moves_rta_to_next_month(
        self, client, db_session, test_family, test_parent_user
    ):
        from app.services.budget.allocation_service import AllocationService

        # Fund the family: one on-budget account with money.
        acct = BudgetAccount(
            family_id=test_family.id, name="Hold Checking", type="checking",
            starting_balance=0,
        )
        db_session.add(acct)
        await db_session.commit()
        from app.models.budget import BudgetTransaction
        db_session.add(BudgetTransaction(
            family_id=test_family.id, account_id=acct.id,
            date=date(2026, 7, 3), amount=100000,  # +$1000 income
        ))
        await db_session.commit()

        rta_july_before = await AllocationService.compute_ready_to_assign(
            db_session, test_family.id, date(2026, 7, 1)
        )

        headers = await _login(client, test_parent_user.email)
        r = await client.post(
            "/api/budget/months/2026/7/hold",
            json={"amount": 30000}, headers=headers,
        )
        assert r.status_code == 200, r.text

        rta_july = await AllocationService.compute_ready_to_assign(
            db_session, test_family.id, date(2026, 7, 1)
        )
        rta_aug = await AllocationService.compute_ready_to_assign(
            db_session, test_family.id, date(2026, 8, 1)
        )
        assert rta_july == rta_july_before - 30000
        # August inherits the base balance; the held money must NOT be
        # double-lost there (it returns to availability).
        assert rta_aug >= rta_july  # held amount released next month

        # Status exposes the hold
        r = await client.get(
            "/api/budget/months/2026/7/status", headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["held_amount"] == 30000

        # Clearing the hold restores RTA
        r = await client.post(
            "/api/budget/months/2026/7/hold",
            json={"amount": 0}, headers=headers,
        )
        assert r.status_code == 200
        rta_after_clear = await AllocationService.compute_ready_to_assign(
            db_session, test_family.id, date(2026, 7, 1)
        )
        assert rta_after_clear == rta_july_before

    @pytest.mark.asyncio
    async def test_hold_rejects_negative(
        self, client, db_session, test_family, test_parent_user
    ):
        headers = await _login(client, test_parent_user.email)
        r = await client.post(
            "/api/budget/months/2026/7/hold",
            json={"amount": -5}, headers=headers,
        )
        assert r.status_code in (400, 422)


class TestCategoryNotes:
    @pytest.mark.asyncio
    async def test_notes_roundtrip(
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
        r = await client.put(
            f"/api/budget/categories/{cat.id}",
            json={"notes": "Solo súper de la semana, no antojos"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "Solo súper de la semana, no antojos"

        r = await client.get(
            f"/api/budget/categories/{cat.id}", headers=headers,
        )
        assert r.json()["notes"] == "Solo súper de la semana, no antojos"
