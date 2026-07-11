"""Actual-Budget-parity fixes (2026-07-10 forensic comparison).

- Receipt scans with ZERO budget accounts land in the drafts queue
  (account_id now nullable) instead of failing with a generic error —
  the real-world "scan is not working" report: vision extracted fine but
  the family had no accounts to attach to.
- Approving an account-less draft requires picking an account.
- Recurring transactions auto-post via the scheduler sweep
  (RecurringTransactionService.post_all_due) — schedules used to require
  a manual "Post now" click forever.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.budget import (
    BudgetAccount,
    BudgetReceiptDraft,
    BudgetTransaction,
)


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestAccountlessDrafts:
    @pytest.mark.asyncio
    async def test_route_to_drafts_with_no_accounts_creates_draft(
        self, db_session, test_family
    ):
        from app.services.budget.receipt_scanner_service import (
            ScannedReceipt,
            _route_to_drafts,
        )

        receipt = ScannedReceipt(
            date="2026-07-10", total_amount=-15550,
            payee_name="SUPERMERCADO QA", items=[], confidence=0.95,
        )
        result = await _route_to_drafts(
            db_session, test_family.id, None, b"fakebytes", receipt,
            {"date": "2026-07-10", "total_amount": -15550,
             "payee_name": "SUPERMERCADO QA"},
            reason="no_accounts",
        )
        # Contract: drafts return success=False + draft_id (the scan page
        # redirects to the review queue when draft_id is present).
        assert result["draft_id"] is not None

        draft = (await db_session.execute(
            select(BudgetReceiptDraft).where(
                BudgetReceiptDraft.family_id == test_family.id
            )
        )).scalar_one()
        assert draft.account_id is None
        assert draft.status == "pending"

    @pytest.mark.asyncio
    async def test_approving_accountless_draft_requires_account(
        self, client, db_session, test_family, test_parent_user
    ):
        draft = BudgetReceiptDraft(
            family_id=test_family.id, account_id=None,
            scanned_data={"date": "2026-07-10", "total_amount": -5000,
                          "payee_name": "QA"},
            confidence=0.9,
        )
        db_session.add(draft)
        await db_session.commit()
        await db_session.refresh(draft)

        headers = await _login(client, test_parent_user.email)

        # The list endpoint must serialize account-less drafts (the response
        # schema used to require a UUID and 500'd the whole review queue).
        r = await client.get("/api/budget/receipt-drafts/", headers=headers)
        assert r.status_code == 200, r.text
        assert any(d["id"] == str(draft.id) for d in r.json())

        r = await client.post(
            f"/api/budget/receipt-drafts/{draft.id}/approve",
            json={}, headers=headers,
        )
        assert r.status_code == 400
        assert "account" in r.text.lower()

        # With an account supplied it approves and creates the transaction.
        acct = BudgetAccount(
            family_id=test_family.id, name="QA Checking",
            type="checking",
        )
        db_session.add(acct)
        await db_session.commit()
        await db_session.refresh(acct)

        r = await client.post(
            f"/api/budget/receipt-drafts/{draft.id}/approve",
            json={"account_id": str(acct.id)}, headers=headers,
        )
        assert r.status_code == 200, r.text

        tx = (await db_session.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.family_id == test_family.id,
                BudgetTransaction.account_id == acct.id,
            )
        )).scalar_one_or_none()
        assert tx is not None
        assert tx.amount == -5000


class TestRecurringAutoPost:
    @pytest.mark.asyncio
    async def test_sweep_posts_due_templates_across_families(
        self, db_session, test_family, test_parent_user
    ):
        """The scheduler sweep posts every family's due recurring templates
        — schedules used to sit until a parent clicked "Post now"."""
        from app.models.budget import BudgetRecurringTransaction
        from app.services.budget.recurring_transaction_service import (
            RecurringTransactionService,
        )

        acct = BudgetAccount(
            family_id=test_family.id, name="RT Checking",
            type="checking",
        )
        db_session.add(acct)
        await db_session.commit()

        rt = BudgetRecurringTransaction(
            family_id=test_family.id, account_id=acct.id,
            name="Netflix QA", amount=-22900,
            recurrence_type="monthly_dayofmonth",
            start_date=date.today() - timedelta(days=40),
            next_due_date=date.today() - timedelta(days=1),
            is_active=True,
        )
        db_session.add(rt)
        await db_session.commit()

        posted = await RecurringTransactionService.post_all_due_all_families(
            db_session
        )
        assert posted >= 1

        tx = (await db_session.execute(
            select(BudgetTransaction).where(
                BudgetTransaction.family_id == test_family.id,
                BudgetTransaction.account_id == acct.id,
            )
        )).scalar_one_or_none()
        assert tx is not None
        assert tx.amount == -22900

        await db_session.refresh(rt)
        assert rt.next_due_date > date.today() - timedelta(days=1)  # advanced

        # Idempotent: nothing left due → second sweep posts nothing new.
        again = await RecurringTransactionService.post_all_due_all_families(
            db_session
        )
        assert again == 0
