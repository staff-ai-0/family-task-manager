"""
Tests for advanced TransactionService methods:
search_transactions, bulk_update_transactions, bulk_delete_transactions,
and finish_reconciliation.
"""

import pytest
from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.budget.transaction_service import TransactionService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.account_service import AccountService
from app.services.budget.payee_service import PayeeService
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryCreate,
    AccountCreate,
    TransactionCreate,
    PayeeCreate,
)


@pytest.fixture
async def budget_data(db: AsyncSession, family_id):
    """Create shared budget entities: group, two categories, account, two payees."""
    group = await CategoryGroupService.create(
        db, family_id,
        CategoryGroupCreate(name="Expenses", is_income=False, sort_order=0),
    )
    cat_groceries = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="Groceries", group_id=group.id, sort_order=0),
    )
    cat_transport = await CategoryService.create(
        db, family_id,
        CategoryCreate(name="Transport", group_id=group.id, sort_order=1),
    )
    account = await AccountService.create(
        db, family_id,
        AccountCreate(name="Checking", type="checking"),
    )
    payee_super = await PayeeService.create(
        db, family_id,
        PayeeCreate(name="Supermarket"),
    )
    payee_gas = await PayeeService.create(
        db, family_id,
        PayeeCreate(name="Gas Station"),
    )
    return {
        "group": group,
        "cat_groceries": cat_groceries,
        "cat_transport": cat_transport,
        "account": account,
        "payee_super": payee_super,
        "payee_gas": payee_gas,
    }


# ---------------------------------------------------------------------------
# search_transactions
# ---------------------------------------------------------------------------


class TestSearchTransactions:
    """Tests for TransactionService.search_transactions"""

    @pytest.mark.asyncio
    async def test_filter_by_payee(self, db: AsyncSession, family_id, budget_data):
        """Filtering by payee_id returns only matching transactions."""
        acct = budget_data["account"]
        payee_super = budget_data["payee_super"]
        payee_gas = budget_data["payee_gas"]

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-5000, payee_id=payee_super.id,
            ),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-3000, payee_id=payee_gas.id,
            ),
        )

        results = await TransactionService.search_transactions(
            db, family_id, payee_id=payee_super.id,
        )

        assert len(results) == 1
        assert results[0].payee_id == payee_super.id

    @pytest.mark.asyncio
    async def test_filter_by_amount_range(self, db: AsyncSession, family_id, budget_data):
        """amount_min / amount_max filters work correctly."""
        acct = budget_data["account"]

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1), amount=-1000,
            ),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2), amount=-5000,
            ),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 3), amount=-10000,
            ),
        )

        results = await TransactionService.search_transactions(
            db, family_id, amount_min=-5000, amount_max=-1000,
        )

        amounts = sorted([r.amount for r in results])
        assert len(results) == 2
        assert amounts == [-5000, -1000]

    @pytest.mark.asyncio
    async def test_filter_by_cleared_status(self, db: AsyncSession, family_id, budget_data):
        """Filtering by cleared=True returns only cleared transactions."""
        acct = budget_data["account"]

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-2000, cleared=True,
            ),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-3000, cleared=False,
            ),
        )

        cleared = await TransactionService.search_transactions(
            db, family_id, cleared=True,
        )
        uncleared = await TransactionService.search_transactions(
            db, family_id, cleared=False,
        )

        assert len(cleared) == 1
        assert cleared[0].cleared is True
        assert len(uncleared) == 1
        assert uncleared[0].cleared is False

    @pytest.mark.asyncio
    async def test_search_in_notes(self, db: AsyncSession, family_id, budget_data):
        """Text search matches against the notes field (case-insensitive)."""
        acct = budget_data["account"]

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-1500, notes="Weekly grocery run",
            ),
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-800, notes="Gas refill",
            ),
        )

        results = await TransactionService.search_transactions(
            db, family_id, search="grocery",
        )

        assert len(results) == 1
        assert "grocery" in results[0].notes.lower()


# ---------------------------------------------------------------------------
# bulk_update_transactions
# ---------------------------------------------------------------------------


class TestBulkUpdateTransactions:
    """Tests for TransactionService.bulk_update_transactions"""

    @pytest.mark.asyncio
    async def test_bulk_clear_transactions(self, db: AsyncSession, family_id, budget_data):
        """Bulk update can mark multiple transactions as cleared."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-1000, cleared=False,
            ),
        )
        t2 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-2000, cleared=False,
            ),
        )

        count = await TransactionService.bulk_update_transactions(
            db, family_id,
            transaction_ids=[t1.id, t2.id],
            updates={"cleared": True},
        )

        assert count == 2

        # Verify they are now cleared
        updated = await TransactionService.search_transactions(
            db, family_id, cleared=True,
        )
        updated_ids = {u.id for u in updated}
        assert t1.id in updated_ids
        assert t2.id in updated_ids

    @pytest.mark.asyncio
    async def test_bulk_category_reassign(self, db: AsyncSession, family_id, budget_data):
        """Bulk update can reassign category on multiple transactions."""
        acct = budget_data["account"]
        cat_groceries = budget_data["cat_groceries"]
        cat_transport = budget_data["cat_transport"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-1000, category_id=cat_groceries.id,
            ),
        )
        t2 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-2000, category_id=cat_groceries.id,
            ),
        )

        count = await TransactionService.bulk_update_transactions(
            db, family_id,
            transaction_ids=[t1.id, t2.id],
            updates={"category_id": str(cat_transport.id)},
        )

        assert count == 2

        # Verify category changed
        results = await TransactionService.search_transactions(
            db, family_id, category_id=cat_transport.id,
        )
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_bulk_update_ignores_disallowed_fields(self, db: AsyncSession, family_id, budget_data):
        """Bulk update silently ignores fields not in the allowed set."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=-1000, notes="original",
            ),
        )

        count = await TransactionService.bulk_update_transactions(
            db, family_id,
            transaction_ids=[t1.id],
            updates={"notes": "hacked", "amount": 999999},
        )

        # No allowed fields were provided, so nothing updated
        assert count == 0

    @pytest.mark.asyncio
    async def test_bulk_update_empty_list(self, db: AsyncSession, family_id, budget_data):
        """Bulk update with empty transaction list returns 0."""
        count = await TransactionService.bulk_update_transactions(
            db, family_id,
            transaction_ids=[],
            updates={"cleared": True},
        )
        assert count == 0


# ---------------------------------------------------------------------------
# bulk_delete_transactions
# ---------------------------------------------------------------------------


class TestBulkDeleteTransactions:
    """Tests for TransactionService.bulk_delete_transactions"""

    @pytest.mark.asyncio
    async def test_bulk_delete_multiple(self, db: AsyncSession, family_id, budget_data):
        """Bulk delete removes multiple transactions and returns correct count."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1), amount=-1000,
            ),
        )
        t2 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2), amount=-2000,
            ),
        )
        t3 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 3), amount=-3000,
            ),
        )

        count = await TransactionService.bulk_delete_transactions(
            db, family_id, transaction_ids=[t1.id, t2.id],
        )

        assert count == 2

        # Only t3 should remain
        remaining = await TransactionService.search_transactions(db, family_id)
        assert len(remaining) == 1
        assert remaining[0].id == t3.id

    @pytest.mark.asyncio
    async def test_bulk_delete_empty_list(self, db: AsyncSession, family_id, budget_data):
        """Bulk delete with empty list returns 0 and deletes nothing."""
        acct = budget_data["account"]

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1), amount=-1000,
            ),
        )

        count = await TransactionService.bulk_delete_transactions(
            db, family_id, transaction_ids=[],
        )

        assert count == 0

        remaining = await TransactionService.search_transactions(db, family_id)
        assert len(remaining) == 1

    @pytest.mark.asyncio
    async def test_bulk_delete_ignores_other_family(self, db: AsyncSession, family_id, budget_data):
        """Bulk delete does not remove transactions from another family."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1), amount=-1000,
            ),
        )

        # Attempt to delete using a random family_id
        other_family = uuid4()
        count = await TransactionService.bulk_delete_transactions(
            db, other_family, transaction_ids=[t1.id],
        )

        assert count == 0

        # Original transaction should still exist
        remaining = await TransactionService.search_transactions(db, family_id)
        assert len(remaining) == 1


# ---------------------------------------------------------------------------
# finish_reconciliation
# ---------------------------------------------------------------------------


class TestFinishReconciliation:
    """Tests for TransactionService.finish_reconciliation"""

    @pytest.mark.asyncio
    async def test_reconciliation_no_adjustment(self, db: AsyncSession, family_id, budget_data):
        """When cleared balance matches statement, no adjustment is created."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=100000, cleared=False,  # $1000 deposit
            ),
        )
        t2 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 2),
                amount=-30000, cleared=False,  # -$300
            ),
        )

        # Statement says $700, which equals 100000 - 30000
        result = await TransactionService.finish_reconciliation(
            db, family_id,
            account_id=acct.id,
            statement_balance=70000,
            transaction_ids=[t1.id, t2.id],
        )

        assert result["reconciled_count"] == 2
        assert result["adjustment_amount"] == 0
        assert result["adjustment_transaction_id"] is None

    @pytest.mark.asyncio
    async def test_reconciliation_with_adjustment(self, db: AsyncSession, family_id, budget_data):
        """When cleared balance differs from statement, an adjustment txn is created."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=100000, cleared=False,  # $1000
            ),
        )

        # Statement says $1050 but we only have $1000 cleared
        # Adjustment should be +5000 ($50)
        result = await TransactionService.finish_reconciliation(
            db, family_id,
            account_id=acct.id,
            statement_balance=105000,
            transaction_ids=[t1.id],
        )

        assert result["reconciled_count"] == 1
        assert result["adjustment_amount"] == 5000  # 105000 - 100000
        assert result["adjustment_transaction_id"] is not None

        # Verify the adjustment transaction exists and is reconciled
        all_txns = await TransactionService.search_transactions(
            db, family_id, account_id=acct.id,
        )
        adjustment = [t for t in all_txns if t.notes == "Ajuste de Conciliaci\u00f3n"]
        assert len(adjustment) == 1
        assert adjustment[0].amount == 5000
        assert adjustment[0].cleared is True
        assert adjustment[0].reconciled is True

    @pytest.mark.asyncio
    async def test_reconciliation_marks_transactions_reconciled(
        self, db: AsyncSession, family_id, budget_data
    ):
        """All provided transactions end up with cleared=True and reconciled=True."""
        acct = budget_data["account"]

        t1 = await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=acct.id, date=date(2026, 3, 1),
                amount=50000, cleared=False,
            ),
        )

        await TransactionService.finish_reconciliation(
            db, family_id,
            account_id=acct.id,
            statement_balance=50000,
            transaction_ids=[t1.id],
        )

        # Refresh to see updated values
        updated = await TransactionService.get_by_id(db, t1.id, family_id)
        assert updated.cleared is True
        assert updated.reconciled is True
