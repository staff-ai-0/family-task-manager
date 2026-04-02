"""
Tests for ReportService and RecurringTransactionService.

Covers:
- ReportService.get_net_worth_history
- ReportService.get_budget_vs_actual
- RecurringTransactionService.post_all_due
"""

import pytest
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.budget.report_service import ReportService
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.services.budget.category_service import CategoryService, CategoryGroupService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.account_service import AccountService
from app.services.budget.transaction_service import TransactionService
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryCreate,
    AllocationCreate,
    AccountCreate,
    TransactionCreate,
    RecurringTransactionCreate,
)


class TestGetNetWorthHistory:
    """Tests for ReportService.get_net_worth_history"""

    @pytest.mark.asyncio
    async def test_net_worth_history_with_transactions(
        self, db: AsyncSession, family_id
    ):
        """Net worth history reflects starting balance plus cumulative transactions."""
        # Create an account with a starting balance of $1000
        account = await AccountService.create(
            db, family_id,
            AccountCreate(
                name="Checking",
                type="checking",
                starting_balance=100_000,  # $1000
            ),
        )

        # Add a transaction two months ago (-$200)
        today = date.today()
        two_months_ago = date(today.year, today.month, 1) - timedelta(days=35)
        tx_date = date(two_months_ago.year, two_months_ago.month, 15)

        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=tx_date,
                amount=-20_000,  # -$200 expense
            ),
        )

        # Add a transaction this month (+$500 income)
        this_month_date = date(today.year, today.month, 5)
        if this_month_date > today:
            this_month_date = today
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=this_month_date,
                amount=50_000,  # +$500 income
            ),
        )

        result = await ReportService.get_net_worth_history(db, family_id, months=3)

        assert "series" in result
        assert "months" in result
        assert "current_net_worth" in result
        assert "current_net_worth_currency" in result

        series = result["series"]
        assert len(series) == 3

        # Each entry should have month label and net_worth
        for entry in series:
            assert "month" in entry
            assert "net_worth" in entry
            assert "net_worth_currency" in entry

        # The last entry (current month) should include all transactions.
        # starting_balance_txn(100000) + tx1(-20000) + tx2(50000) = 130000
        current = series[-1]
        assert current["net_worth"] == 130_000
        assert current["net_worth_currency"] == 1300.0

    @pytest.mark.asyncio
    async def test_net_worth_history_no_accounts(self, db: AsyncSession, family_id):
        """Returns empty series when no accounts exist."""
        result = await ReportService.get_net_worth_history(db, family_id, months=6)

        assert result["series"] == []
        assert result["current_net_worth"] == 0

    @pytest.mark.asyncio
    async def test_net_worth_history_closed_accounts_excluded(
        self, db: AsyncSession, family_id
    ):
        """Closed accounts are excluded from net worth history."""
        # Create open account
        open_acct = await AccountService.create(
            db, family_id,
            AccountCreate(
                name="Open Checking",
                type="checking",
                starting_balance=50_000,
            ),
        )

        # Create closed account
        closed_acct = await AccountService.create(
            db, family_id,
            AccountCreate(
                name="Old Savings",
                type="savings",
                starting_balance=200_000,
                closed=True,
            ),
        )

        result = await ReportService.get_net_worth_history(db, family_id, months=1)

        series = result["series"]
        assert len(series) == 1
        # Only the open account's starting balance transaction should be counted
        assert series[0]["net_worth"] == 50_000


class TestGetBudgetVsActual:
    """Tests for ReportService.get_budget_vs_actual"""

    @pytest.mark.asyncio
    async def test_budget_vs_actual_basic(self, db: AsyncSession, family_id):
        """Returns budgeted, actual, variance, and pct_used per category."""
        # Create expense group and category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Bills", is_income=False, sort_order=0),
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(
                name="Electricity",
                group_id=group.id,
                sort_order=0,
            ),
        )

        # Create an account for transactions
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Main Checking", type="checking"),
        )

        month = date(2026, 3, 1)

        # Set budget allocation: $300
        await AllocationService.set_category_budget(
            db, family_id, category.id, month, 30_000,
        )

        # Create a spending transaction: -$120
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 3, 10),
                amount=-12_000,
                category_id=category.id,
            ),
        )

        result = await ReportService.get_budget_vs_actual(db, family_id, month)

        assert result["month"] == "2026-03-01"
        assert "groups" in result
        assert "totals" in result

        # Find our group
        assert len(result["groups"]) >= 1
        grp = result["groups"][0]
        assert grp["group_name"] == "Bills"
        assert len(grp["categories"]) >= 1

        cat_entry = grp["categories"][0]
        assert cat_entry["category_name"] == "Electricity"
        assert cat_entry["budgeted"] == 30_000
        # actual should be the absolute value of spending
        assert cat_entry["actual"] == 12_000
        # variance = budgeted - actual = 30000 - 12000 = 18000 (under budget)
        assert cat_entry["variance"] == 18_000
        # pct_used = 12000 / 30000 * 100 = 40.0
        assert cat_entry["pct_used"] == 40.0

        # Totals
        assert result["totals"]["budgeted"] == 30_000
        assert result["totals"]["actual"] == 12_000
        assert result["totals"]["variance"] == 18_000

    @pytest.mark.asyncio
    async def test_budget_vs_actual_no_categories(self, db: AsyncSession, family_id):
        """Returns empty groups when no expense categories exist."""
        month = date(2026, 3, 1)
        result = await ReportService.get_budget_vs_actual(db, family_id, month)

        assert result["month"] == "2026-03-01"
        assert result["groups"] == []

    @pytest.mark.asyncio
    async def test_budget_vs_actual_excludes_income_groups(
        self, db: AsyncSession, family_id
    ):
        """Income category groups are excluded from budget vs actual."""
        # Create income group
        income_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True, sort_order=0),
        )
        await CategoryService.create(
            db, family_id,
            CategoryCreate(
                name="Salary",
                group_id=income_group.id,
                sort_order=0,
            ),
        )

        # Create expense group
        expense_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Housing", is_income=False, sort_order=1),
        )
        await CategoryService.create(
            db, family_id,
            CategoryCreate(
                name="Rent",
                group_id=expense_group.id,
                sort_order=0,
            ),
        )

        month = date(2026, 3, 1)
        result = await ReportService.get_budget_vs_actual(db, family_id, month)

        group_names = [g["group_name"] for g in result["groups"]]
        assert "Income" not in group_names
        assert "Housing" in group_names

    @pytest.mark.asyncio
    async def test_budget_vs_actual_no_budget_zero_pct(
        self, db: AsyncSession, family_id
    ):
        """pct_used is None when budgeted amount is zero."""
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Fun", is_income=False, sort_order=0),
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(
                name="Entertainment",
                group_id=group.id,
                sort_order=0,
            ),
        )

        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Card", type="checking"),
        )

        month = date(2026, 3, 1)
        # No allocation set (budgeted = 0), but there is spending
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 3, 15),
                amount=-5_000,
                category_id=category.id,
            ),
        )

        result = await ReportService.get_budget_vs_actual(db, family_id, month)
        cat_entry = result["groups"][0]["categories"][0]
        assert cat_entry["budgeted"] == 0
        assert cat_entry["actual"] == 5_000
        assert cat_entry["pct_used"] is None


class TestPostAllDue:
    """Tests for RecurringTransactionService.post_all_due"""

    @pytest.mark.asyncio
    async def test_post_all_due_with_one_due_template(
        self, db: AsyncSession, family_id
    ):
        """Posts a transaction when a recurring template is due."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking"),
        )

        # Create a recurring template that started in the past and is due today
        today = date.today()
        start = today - timedelta(days=30)

        recurring = await RecurringTransactionService.create(
            db, family_id,
            RecurringTransactionCreate(
                account_id=account.id,
                name="Monthly Rent",
                amount=-15_000_00,  # -$15000
                recurrence_type="monthly_dayofmonth",
                recurrence_interval=1,
                recurrence_pattern={"day": today.day},
                start_date=start,
                is_active=True,
            ),
        )

        # Force next_due_date to today so it triggers
        recurring.next_due_date = today
        await db.commit()

        result = await RecurringTransactionService.post_all_due(
            db, family_id, as_of_date=today
        )

        assert result["posted"] == 1
        assert len(result["transactions"]) == 1

        tx_info = result["transactions"][0]
        assert tx_info["recurring_name"] == "Monthly Rent"
        assert tx_info["amount"] == -15_000_00
        assert tx_info["date"] == str(today)

    @pytest.mark.asyncio
    async def test_post_all_due_no_due_templates(self, db: AsyncSession, family_id):
        """Returns posted=0 when no templates are due."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Savings", type="savings"),
        )

        # Create a template with next_due_date far in the future
        future_start = date.today() + timedelta(days=60)
        await RecurringTransactionService.create(
            db, family_id,
            RecurringTransactionCreate(
                account_id=account.id,
                name="Future Payment",
                amount=-5_000,
                recurrence_type="monthly_dayofmonth",
                recurrence_interval=1,
                recurrence_pattern={"day": future_start.day},
                start_date=future_start,
                is_active=True,
            ),
        )

        result = await RecurringTransactionService.post_all_due(
            db, family_id, as_of_date=date.today()
        )

        assert result["posted"] == 0
        assert result["transactions"] == []

    @pytest.mark.asyncio
    async def test_post_all_due_inactive_template_skipped(
        self, db: AsyncSession, family_id
    ):
        """Inactive recurring templates are not posted even if due."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking"),
        )

        today = date.today()
        start = today - timedelta(days=10)

        recurring = await RecurringTransactionService.create(
            db, family_id,
            RecurringTransactionCreate(
                account_id=account.id,
                name="Cancelled Sub",
                amount=-1_000,
                recurrence_type="monthly_dayofmonth",
                recurrence_interval=1,
                recurrence_pattern={"day": today.day},
                start_date=start,
                is_active=False,
            ),
        )

        result = await RecurringTransactionService.post_all_due(
            db, family_id, as_of_date=today
        )

        assert result["posted"] == 0
        assert result["transactions"] == []

    @pytest.mark.asyncio
    async def test_post_all_due_multiple_templates(self, db: AsyncSession, family_id):
        """Posts transactions for multiple due templates in one call."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking"),
        )

        today = date.today()
        start = today - timedelta(days=30)

        # Create two due recurring templates
        for name, amount in [("Rent", -10_000), ("Internet", -1_500)]:
            rec = await RecurringTransactionService.create(
                db, family_id,
                RecurringTransactionCreate(
                    account_id=account.id,
                    name=name,
                    amount=amount,
                    recurrence_type="monthly_dayofmonth",
                    recurrence_interval=1,
                    recurrence_pattern={"day": today.day},
                    start_date=start,
                    is_active=True,
                ),
            )
            # Force due today
            rec.next_due_date = today
            await db.commit()

        result = await RecurringTransactionService.post_all_due(
            db, family_id, as_of_date=today
        )

        assert result["posted"] == 2
        assert len(result["transactions"]) == 2
        names = {t["recurring_name"] for t in result["transactions"]}
        assert names == {"Rent", "Internet"}
