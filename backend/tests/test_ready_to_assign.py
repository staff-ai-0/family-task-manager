"""
Tests for the envelope budgeting "Ready to Assign" calculation.

Verifies that ready_to_assign = total_on_budget_balance
                                 - expense_budgeted_this_month
                                 - (prior_expense_budgeted + prior_expense_activity)
"""

import pytest
from datetime import date
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.budget.allocation_service import AllocationService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.transaction_service import TransactionService
from app.services.budget.account_service import AccountService
from app.schemas.budget import (
    CategoryGroupCreate,
    CategoryCreate,
    AllocationCreate,
    AccountCreate,
    TransactionCreate,
)


class TestReadyToAssign:
    """Test the core envelope budgeting ready_to_assign calculation components."""

    @pytest.mark.asyncio
    async def test_total_on_budget_balance_empty(self, db: AsyncSession, family_id):
        """With no accounts or transactions, total on-budget balance is 0."""
        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 0

    @pytest.mark.asyncio
    async def test_total_on_budget_balance_single_account(self, db: AsyncSession, family_id):
        """Balance equals sum of transactions in on-budget account."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Create a group and category for the transactions
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True, sort_order=0)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Salary", group_id=group.id)
        )

        # Deposit $1,000
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 3, 1),
                amount=100_000,  # $1,000 in cents
                category_id=category.id,
            )
        )

        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 100_000

    @pytest.mark.asyncio
    async def test_offbudget_account_excluded(self, db: AsyncSession, family_id):
        """Transactions in off-budget accounts are NOT counted."""
        on_budget = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", offbudget=False)
        )
        off_budget = await AccountService.create(
            db, family_id,
            AccountCreate(name="Savings (off)", type="savings", offbudget=True)
        )

        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Salary", group_id=group.id)
        )

        # $500 on-budget
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=on_budget.id,
                date=date(2026, 3, 1),
                amount=50_000,
                category_id=category.id,
            )
        )
        # $9,000 off-budget (should NOT count)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=off_budget.id,
                date=date(2026, 3, 1),
                amount=900_000,
                category_id=category.id,
            )
        )

        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 50_000  # Only on-budget account

    @pytest.mark.asyncio
    async def test_starting_balance_auto_transaction(self, db: AsyncSession, family_id):
        """Creating an account with starting_balance creates a Starting Balance transaction."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=500_000)
        )

        assert account.starting_balance == 500_000

        # The total on-budget balance should reflect the starting balance transaction
        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 500_000

    @pytest.mark.asyncio
    async def test_starting_balance_zero_no_transaction(self, db: AsyncSession, family_id):
        """Creating an account with starting_balance=0 does NOT create a transaction."""
        await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=0)
        )

        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 0

    @pytest.mark.asyncio
    async def test_get_total_expense_budgeted_for_month(self, db: AsyncSession, family_id):
        """Only expense category allocations count (income category excluded)."""
        expense_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Housing", is_income=False)
        )
        income_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True)
        )
        expense_cat = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Rent", group_id=expense_group.id)
        )
        income_cat = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Salary", group_id=income_group.id)
        )

        month = date(2026, 3, 1)
        await AllocationService.set_category_budget(db, family_id, expense_cat.id, month, 200_000)
        await AllocationService.set_category_budget(db, family_id, income_cat.id, month, 500_000)

        total = await AllocationService.get_total_expense_budgeted_for_month(db, family_id, month)
        assert total == 200_000  # Only expense, not income

    @pytest.mark.asyncio
    async def test_prior_expense_activity_excludes_income_categories(self, db: AsyncSession, family_id):
        """Income category transactions are NOT included in prior_expense_activity."""
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )
        expense_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        income_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True)
        )
        expense_cat = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=expense_group.id)
        )
        income_cat = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Salary", group_id=income_group.id)
        )

        # Feb: deposit $10,000 income + spend $500 expenses
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 1),
                amount=1_000_000,
                category_id=income_cat.id,
            )
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-50_000,
                category_id=expense_cat.id,
            )
        )

        current_month = date(2026, 3, 1)
        activity = await AllocationService.get_total_expense_activity_before_month(
            db, family_id, current_month
        )
        # Only the expense transaction (-50_000) should be included, not the income
        assert activity == -50_000

    @pytest.mark.asyncio
    async def test_null_category_transaction_counts_in_balance(self, db: AsyncSession, family_id):
        """
        Transactions with category_id=NULL (like SAP payroll) still count toward
        total_on_budget_balance — they just don't appear in any category's activity.
        This is the key fix for the -$3,000 bug.
        """
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Transaction with no category (like payroll deposit with NULL category_id)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 3, 1),
                amount=2_342_340_000,  # ~$23M in cents
                category_id=None,
            )
        )

        balance = await AccountService.get_total_on_budget_balance(db, family_id)
        assert balance == 2_342_340_000

    @pytest.mark.asyncio
    async def test_ready_to_assign_formula_full(self, db: AsyncSession, family_id):
        """
        End-to-end test of the ready_to_assign formula:
            ready = total_balance - this_month_budgeted - (prior_budgeted + prior_activity)
        """
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )
        expense_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=expense_group.id, rollover_enabled=False)
        )

        # Feb: deposit $2,000, budget $1,000, spend $800 → leftover $200 but no rollover
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 1),
                amount=200_000,  # $2,000
                category_id=None,
            )
        )
        await AllocationService.set_category_budget(
            db, family_id, category.id, date(2026, 2, 1), 100_000  # budget $1,000
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-80_000,  # spend $800
                category_id=category.id,
            )
        )

        # March: budget $500 for groceries
        march = date(2026, 3, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, march, 50_000  # $500
        )

        # Compute components
        from datetime import timedelta
        end_of_march = date(2026, 3, 31)
        total_balance = await AccountService.get_total_on_budget_balance(
            db, family_id, end_of_march
        )
        expense_budgeted_this_month = await AllocationService.get_total_expense_budgeted_for_month(
            db, family_id, march
        )
        prior_expense_budgeted = await AllocationService.get_total_expense_budgeted_before_month(
            db, family_id, march
        )
        prior_expense_activity = await AllocationService.get_total_expense_activity_before_month(
            db, family_id, march
        )
        prior_net = prior_expense_budgeted + prior_expense_activity
        ready = total_balance - expense_budgeted_this_month - prior_net

        # total_balance = 200_000 - 80_000 = 120_000
        # expense_budgeted_this_month = 50_000
        # prior_net = 100_000 + (-80_000) = 20_000  (leftover from Feb)
        # ready = 120_000 - 50_000 - 20_000 = 50_000
        assert total_balance == 120_000
        assert expense_budgeted_this_month == 50_000
        assert prior_net == 20_000
        assert ready == 50_000
