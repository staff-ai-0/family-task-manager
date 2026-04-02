"""
Tests for advanced AllocationService methods:
  - copy_from_month
  - fill_from_average
  - carry_over_month
"""

import pytest
from datetime import date

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
from app.core.exceptions import ValidationException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_expense_group(db, family_id, name="Expenses"):
    return await CategoryGroupService.create(
        db, family_id,
        CategoryGroupCreate(name=name, is_income=False, sort_order=0),
    )


async def _make_category(db, family_id, group_id, name="Groceries", **kwargs):
    return await CategoryService.create(
        db, family_id,
        CategoryCreate(
            name=name,
            group_id=group_id,
            rollover_enabled=kwargs.get("rollover_enabled", True),
            goal_amount=kwargs.get("goal_amount", 0),
            sort_order=kwargs.get("sort_order", 0),
        ),
    )


async def _make_account(db, family_id, name="Checking"):
    return await AccountService.create(
        db, family_id,
        AccountCreate(name=name, type="checking"),
    )


async def _add_transaction(db, family_id, account_id, category_id, amount, tx_date):
    return await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account_id,
            date=tx_date,
            amount=amount,
            category_id=category_id,
        ),
    )


# ===========================================================================
# copy_from_month
# ===========================================================================

class TestCopyFromMonth:

    @pytest.mark.asyncio
    async def test_basic_copy(self, db: AsyncSession, family_id):
        """Allocations from the source month are duplicated to the target month."""
        group = await _make_expense_group(db, family_id)
        cat_a = await _make_category(db, family_id, group.id, name="Rent")
        cat_b = await _make_category(db, family_id, group.id, name="Utilities")

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        await AllocationService.set_category_budget(db, family_id, cat_a.id, source, 100_00)
        await AllocationService.set_category_budget(db, family_id, cat_b.id, source, 50_00)

        result = await AllocationService.copy_from_month(db, family_id, source, target)

        assert result["copied"] == 2
        assert result["skipped"] == 0

        # Verify amounts in target month
        allocs = await AllocationService.list_by_month(db, family_id, target)
        amounts = {a.category_id: a.budgeted_amount for a in allocs}
        assert amounts[cat_a.id] == 100_00
        assert amounts[cat_b.id] == 50_00

    @pytest.mark.asyncio
    async def test_no_overwrite_skips_existing(self, db: AsyncSession, family_id):
        """With overwrite=False, categories that already have a non-zero allocation are skipped."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Rent")

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        await AllocationService.set_category_budget(db, family_id, cat.id, source, 100_00)
        # Pre-set a different amount in the target month
        await AllocationService.set_category_budget(db, family_id, cat.id, target, 75_00)

        result = await AllocationService.copy_from_month(
            db, family_id, source, target, overwrite=False,
        )

        assert result["copied"] == 0
        assert result["skipped"] == 1

        # Target allocation should remain untouched
        allocs = await AllocationService.list_by_month(db, family_id, target)
        assert allocs[0].budgeted_amount == 75_00

    @pytest.mark.asyncio
    async def test_overwrite_replaces_existing(self, db: AsyncSession, family_id):
        """With overwrite=True, existing target allocations are replaced."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Rent")

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        await AllocationService.set_category_budget(db, family_id, cat.id, source, 100_00)
        await AllocationService.set_category_budget(db, family_id, cat.id, target, 75_00)

        result = await AllocationService.copy_from_month(
            db, family_id, source, target, overwrite=True,
        )

        assert result["copied"] == 1
        assert result["skipped"] == 0

        allocs = await AllocationService.list_by_month(db, family_id, target)
        assert allocs[0].budgeted_amount == 100_00

    @pytest.mark.asyncio
    async def test_zero_source_allocations_are_skipped(self, db: AsyncSession, family_id):
        """Source allocations with a zero amount are skipped (not copied)."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Misc")

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        # Create an allocation with zero amount
        await AllocationService.set_category_budget(db, family_id, cat.id, source, 0)

        result = await AllocationService.copy_from_month(db, family_id, source, target)

        assert result["copied"] == 0
        assert result["skipped"] == 1


# ===========================================================================
# fill_from_average
# ===========================================================================

class TestFillFromAverage:

    @pytest.mark.asyncio
    async def test_average_from_three_months(self, db: AsyncSession, family_id):
        """Average spending over 3 months is computed and set as the budget."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Groceries")
        account = await _make_account(db, family_id)

        # Spending in Jan, Feb, Mar (negative = expense)
        await _add_transaction(db, family_id, account.id, cat.id, -300_00, date(2026, 1, 15))
        await _add_transaction(db, family_id, account.id, cat.id, -600_00, date(2026, 2, 15))
        await _add_transaction(db, family_id, account.id, cat.id, -900_00, date(2026, 3, 15))

        target = date(2026, 4, 1)
        result = await AllocationService.fill_from_average(
            db, family_id, target, months_back=3,
        )

        assert result["filled"] == 1
        assert result["skipped"] == 0

        # Average absolute spending: (300 + 600 + 900) / 3 = 600  (in dollars, 60000 cents)
        allocs = await AllocationService.list_by_month(db, family_id, target)
        assert len(allocs) == 1
        assert allocs[0].budgeted_amount == 600_00

    @pytest.mark.asyncio
    async def test_no_overwrite_skips_existing(self, db: AsyncSession, family_id):
        """With overwrite=False, categories with a non-zero allocation are skipped."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Groceries")
        account = await _make_account(db, family_id)

        await _add_transaction(db, family_id, account.id, cat.id, -300_00, date(2026, 1, 15))

        target = date(2026, 4, 1)
        # Pre-set an allocation in the target month
        await AllocationService.set_category_budget(db, family_id, cat.id, target, 999_00)

        result = await AllocationService.fill_from_average(
            db, family_id, target, months_back=3, overwrite=False,
        )

        assert result["filled"] == 0
        assert result["skipped"] == 1

        # Existing allocation should be untouched
        allocs = await AllocationService.list_by_month(db, family_id, target)
        assert allocs[0].budgeted_amount == 999_00

    @pytest.mark.asyncio
    async def test_income_categories_excluded(self, db: AsyncSession, family_id):
        """Income category groups are not filled."""
        income_group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Income", is_income=True, sort_order=0),
        )
        income_cat = await _make_category(
            db, family_id, income_group.id, name="Salary",
        )
        account = await _make_account(db, family_id)

        # Income transaction (positive)
        await _add_transaction(db, family_id, account.id, income_cat.id, 5000_00, date(2026, 1, 15))

        target = date(2026, 4, 1)
        result = await AllocationService.fill_from_average(
            db, family_id, target, months_back=3,
        )

        # Income categories should not be filled
        assert result["filled"] == 0

    @pytest.mark.asyncio
    async def test_no_spending_history_skips(self, db: AsyncSession, family_id):
        """Categories with no spending history are skipped."""
        group = await _make_expense_group(db, family_id)
        await _make_category(db, family_id, group.id, name="Unused")

        target = date(2026, 4, 1)
        result = await AllocationService.fill_from_average(
            db, family_id, target, months_back=3,
        )

        assert result["filled"] == 0
        assert result["skipped"] == 1


# ===========================================================================
# carry_over_month
# ===========================================================================

class TestCarryOverMonth:

    @pytest.mark.asyncio
    async def test_basic_carry_over_unspent(self, db: AsyncSession, family_id):
        """Unspent budget from source is added to the target allocation."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Groceries")
        account = await _make_account(db, family_id)

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        # Budget $500, spend $300 -> available = $200 unspent
        await AllocationService.set_category_budget(db, family_id, cat.id, source, 500_00)
        await _add_transaction(db, family_id, account.id, cat.id, -300_00, date(2026, 1, 15))

        result = await AllocationService.carry_over_month(
            db, family_id, source, target, mode="all",
        )

        assert result["carried"] == 1

        # Target should have 0 (original) + 200_00 (available) = 200_00
        allocs = await AllocationService.list_by_month(db, family_id, target)
        target_amounts = {a.category_id: a.budgeted_amount for a in allocs}
        assert target_amounts[cat.id] == 200_00

    @pytest.mark.asyncio
    async def test_unspent_only_skips_overspent(self, db: AsyncSession, family_id):
        """mode='unspent_only' skips categories that are overspent (available < 0)."""
        group = await _make_expense_group(db, family_id)
        cat_under = await _make_category(db, family_id, group.id, name="Underspent")
        cat_over = await _make_category(db, family_id, group.id, name="Overspent", sort_order=1)
        account = await _make_account(db, family_id)

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        # Underspent: budget $500, spend $300 -> available $200
        await AllocationService.set_category_budget(db, family_id, cat_under.id, source, 500_00)
        await _add_transaction(db, family_id, account.id, cat_under.id, -300_00, date(2026, 1, 15))

        # Overspent: budget $200, spend $400 -> available -$200
        await AllocationService.set_category_budget(db, family_id, cat_over.id, source, 200_00)
        await _add_transaction(db, family_id, account.id, cat_over.id, -400_00, date(2026, 1, 20))

        result = await AllocationService.carry_over_month(
            db, family_id, source, target, mode="unspent_only",
        )

        assert result["carried"] == 1
        assert result["skipped"] >= 1  # at least the overspent category

        # Only underspent should have been carried over
        allocs = await AllocationService.list_by_month(db, family_id, target)
        target_amounts = {a.category_id: a.budgeted_amount for a in allocs}
        assert target_amounts[cat_under.id] == 200_00
        # Overspent category should remain at 0 (the default from get_or_create)
        assert target_amounts.get(cat_over.id, 0) == 0

    @pytest.mark.asyncio
    async def test_invalid_mode_raises_validation(self, db: AsyncSession, family_id):
        """An unrecognized mode raises ValidationException."""
        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        with pytest.raises(ValidationException):
            await AllocationService.carry_over_month(
                db, family_id, source, target, mode="bogus_mode",
            )

    @pytest.mark.asyncio
    async def test_carry_over_with_existing_target_budget(self, db: AsyncSession, family_id):
        """Carry over adds to existing target budget (new_amount = target_budgeted + available)."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Groceries")
        account = await _make_account(db, family_id)

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        # Source: budget $500, spend $300 -> available $200
        await AllocationService.set_category_budget(db, family_id, cat.id, source, 500_00)
        await _add_transaction(db, family_id, account.id, cat.id, -300_00, date(2026, 1, 15))

        # Pre-set target to $100
        await AllocationService.set_category_budget(db, family_id, cat.id, target, 100_00)

        result = await AllocationService.carry_over_month(
            db, family_id, source, target, mode="all",
        )

        assert result["carried"] == 1

        # Target should be max(0, 100_00 + 200_00) = 300_00
        allocs = await AllocationService.list_by_month(db, family_id, target)
        target_amounts = {a.category_id: a.budgeted_amount for a in allocs}
        assert target_amounts[cat.id] == 300_00

    @pytest.mark.asyncio
    async def test_carry_over_negative_floors_at_zero(self, db: AsyncSession, family_id):
        """When available is negative and exceeds existing target budget, floor at 0."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(db, family_id, group.id, name="Groceries")
        account = await _make_account(db, family_id)

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        # Source: budget $100, spend $500 -> available -$400
        await AllocationService.set_category_budget(db, family_id, cat.id, source, 100_00)
        await _add_transaction(db, family_id, account.id, cat.id, -500_00, date(2026, 1, 15))

        # Pre-set target to $200
        await AllocationService.set_category_budget(db, family_id, cat.id, target, 200_00)

        result = await AllocationService.carry_over_month(
            db, family_id, source, target, mode="all",
        )

        assert result["carried"] == 1

        # max(0, 200_00 + (-400_00)) = max(0, -200_00) = 0
        allocs = await AllocationService.list_by_month(db, family_id, target)
        target_amounts = {a.category_id: a.budgeted_amount for a in allocs}
        assert target_amounts[cat.id] == 0

    @pytest.mark.asyncio
    async def test_hidden_categories_skipped(self, db: AsyncSession, family_id):
        """Hidden categories are always skipped regardless of mode."""
        group = await _make_expense_group(db, family_id)
        cat = await _make_category(
            db, family_id, group.id, name="HiddenCat",
        )
        # Hide the category after creation
        from app.schemas.budget import CategoryUpdate
        await CategoryService.update(db, cat.id, family_id, CategoryUpdate(hidden=True))

        account = await _make_account(db, family_id)

        source = date(2026, 1, 1)
        target = date(2026, 2, 1)

        await AllocationService.set_category_budget(db, family_id, cat.id, source, 500_00)

        result = await AllocationService.carry_over_month(
            db, family_id, source, target, mode="all",
        )

        assert result["skipped"] >= 1
        assert result["carried"] == 0
