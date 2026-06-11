"""C4: the account-list endpoint must not run an N+1 (one get_balance per account).

AccountService.get_balances_for_accounts is the batched replacement — same numbers
as get_balance, in a constant number of queries.
"""
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.budget.account_service import AccountService
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import AccountCreate, TransactionCreate


async def _seed_accounts(db: AsyncSession, family_id, n=3):
    accounts = []
    for i in range(n):
        a = await AccountService.create(
            db, family_id, AccountCreate(name=f"Acct{i}", type="checking")
        )
        accounts.append(a)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(account_id=a.id, date=date(2026, 2, 1), amount=10000 + i),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(account_id=a.id, date=date(2026, 2, 2), amount=-(3000 + i)),
        )
    return accounts


class TestAccountBalanceBatch:
    @pytest.mark.asyncio
    async def test_batched_equals_per_account(self, db: AsyncSession, family_id):
        accounts = await _seed_accounts(db, family_id, 3)
        ref = {
            a.id: await AccountService.get_balance(db, a.id, family_id) for a in accounts
        }
        batched = await AccountService.get_balances_for_accounts(
            db, [a.id for a in accounts], family_id
        )
        assert set(batched.keys()) == set(ref.keys())
        for aid, exp in ref.items():
            got = batched[aid]
            for field in ("balance", "cleared_balance", "uncleared_balance"):
                assert got[field] == exp[field], f"{field} mismatch for {aid}"

    @pytest.mark.asyncio
    async def test_query_count_is_constant(self, db: AsyncSession, family_id, monkeypatch):
        accounts = await _seed_accounts(db, family_id, 4)
        calls = {"n": 0}
        original = db.execute

        async def counting(*a, **k):
            calls["n"] += 1
            return await original(*a, **k)

        monkeypatch.setattr(db, "execute", counting)
        await AccountService.get_balances_for_accounts(
            db, [a.id for a in accounts], family_id
        )
        assert calls["n"] <= 3, (
            f"{calls['n']} queries for {len(accounts)} accounts — N+1 not eliminated"
        )
