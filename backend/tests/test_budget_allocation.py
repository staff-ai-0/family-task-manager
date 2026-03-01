"""
Tests for budget allocation service with envelope budgeting logic.

Tests the recursive rollover calculation that implements
proper envelope budgeting behavior (available = previous + budgeted + activity).
"""

import pytest
from datetime import date
from uuid import uuid4
from decimal import Decimal

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


class TestCategoryAvailableAmount:
    """Test calculation of available amount with rollover"""

    @pytest.mark.asyncio
    async def test_available_with_no_previous_balance(self, db: AsyncSession, family_id):
        """Test available = budgeted when no previous balance exists"""
        # Create expense group
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False, sort_order=0)
        )

        # Create category with rollover enabled
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(
                name="Groceries",
                group_id=group.id,
                rollover_enabled=True,
                goal_amount=0,
                sort_order=0
            )
        )

        # Set budget for Feb 2026
        month = date(2026, 2, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, month, 50000  # $500
        )

        # Get available for Feb
        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, month
        )

        assert result["budgeted"] == 50000
        assert result["activity"] == 0
        assert result["previous_balance"] == 0
        assert result["available"] == 50000  # 0 + 50000 + 0
        assert result["rollover_enabled"] is True

    @pytest.mark.asyncio
    async def test_available_with_spending(self, db: AsyncSession, family_id):
        """Test available = budgeted + activity (spending reduces available)"""
        # Create account and category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Set budget for Feb 2026
        month = date(2026, 2, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, month, 50000  # $500
        )

        # Add a transaction (spending $150)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-15000,  # -$150
                category_id=category.id
            )
        )

        # Get available for Feb
        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, month
        )

        assert result["budgeted"] == 50000
        assert result["activity"] == -15000
        assert result["available"] == 35000  # 0 + 50000 + (-15000)

    @pytest.mark.asyncio
    async def test_available_with_rollover(self, db: AsyncSession, family_id):
        """Test available = previous_balance + budgeted when rollover is enabled"""
        # Create category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id, rollover_enabled=True)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Jan budget: $500
        jan_month = date(2026, 1, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, jan_month, 50000
        )

        # Jan spending: $350 (leaving $150 unspent)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 1, 15),
                amount=-35000,
                category_id=category.id
            )
        )

        # Feb budget: $200
        feb_month = date(2026, 2, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, feb_month, 20000
        )

        # Get available for Feb (should include Jan's $150 rollover)
        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, feb_month
        )

        # previous_balance = sum of all prior months' budgeted + activity
        # = (50000 - 35000) = 15000
        assert result["budgeted"] == 20000
        assert result["activity"] == 0
        assert result["previous_balance"] == 15000  # Unspent from Jan
        assert result["available"] == 35000  # 15000 + 20000 + 0

    @pytest.mark.asyncio
    async def test_no_rollover_when_disabled(self, db: AsyncSession, family_id):
        """Test previous balance is ignored when rollover_enabled=False"""
        # Create category with rollover disabled
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id, rollover_enabled=False)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Jan budget: $500, spending: $350
        jan_month = date(2026, 1, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, jan_month, 50000
        )
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 1, 15),
                amount=-35000,
                category_id=category.id
            )
        )

        # Feb budget: $200
        feb_month = date(2026, 2, 1)
        await AllocationService.set_category_budget(
            db, family_id, category.id, feb_month, 20000
        )

        # Get available for Feb (should NOT include Jan's balance)
        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, feb_month
        )

        assert result["previous_balance"] == 0  # No rollover
        assert result["available"] == 20000  # Just Feb's budget

    @pytest.mark.asyncio
    async def test_multi_month_rollover_chain(self, db: AsyncSession, family_id):
        """Test rollover across multiple months accumulates properly"""
        # Create category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id, rollover_enabled=True)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Jan: Budget $500, spend $300 (leaves $200)
        jan = date(2026, 1, 1)
        await AllocationService.set_category_budget(db, family_id, category.id, jan, 50000)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 1, 15),
                amount=-30000,
                category_id=category.id
            )
        )

        # Feb: Budget $200, spend $100 (leaves $300 from Jan + $100 unspent = $300 to roll to Mar)
        feb = date(2026, 2, 1)
        await AllocationService.set_category_budget(db, family_id, category.id, feb, 20000)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-10000,
                category_id=category.id
            )
        )

        # Mar: Budget $100, check available includes all previous rolls
        mar = date(2026, 3, 1)
        await AllocationService.set_category_budget(db, family_id, category.id, mar, 10000)

        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, mar
        )

        # previous_balance = sum of all allocations and activities before Mar
        # Jan: 50000 - 30000 = 20000
        # Feb: 20000 - 10000 = 10000
        # Total: 20000 + 10000 = 30000
        assert result["previous_balance"] == 30000
        assert result["budgeted"] == 10000
        assert result["available"] == 40000  # 30000 + 10000

    @pytest.mark.asyncio
    async def test_negative_available_overspending(self, db: AsyncSession, family_id):
        """Test available can be negative if category is overspent"""
        # Create category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Budget $100 but spend $200
        month = date(2026, 2, 1)
        await AllocationService.set_category_budget(db, family_id, category.id, month, 10000)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-20000,
                category_id=category.id
            )
        )

        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, month
        )

        assert result["available"] == -10000  # Over budget by $100

    @pytest.mark.asyncio
    async def test_zero_budgets_with_activity(self, db: AsyncSession, family_id):
        """Test available calculation when category has activity but zero budgets"""
        # Create category
        group = await CategoryGroupService.create(
            db, family_id,
            CategoryGroupCreate(name="Food", is_income=False)
        )
        category = await CategoryService.create(
            db, family_id,
            CategoryCreate(name="Groceries", group_id=group.id)
        )
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking")
        )

        # Spend $50 without setting a budget
        month = date(2026, 2, 1)
        await TransactionService.create(
            db, family_id,
            TransactionCreate(
                account_id=account.id,
                date=date(2026, 2, 15),
                amount=-5000,
                category_id=category.id
            )
        )

        result = await AllocationService.get_category_available_amount(
            db, family_id, category.id, month
        )

        assert result["budgeted"] == 0
        assert result["activity"] == -5000
        assert result["available"] == -5000  # Overspent

