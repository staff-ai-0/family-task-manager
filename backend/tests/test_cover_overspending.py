"""
Tests for month rollover carry (positive + negative) and the
cover-overspending flow (move available between categories in one month).

Covers AllocationService.cover_overspending plus the rollover math that
carries a category's leftover / overspend into the next month's available.
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
from app.core.exceptions import NotFoundException, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_expense_category(db, family_id, name="Groceries", rollover=True):
    group = await CategoryGroupService.create(
        db, family_id,
        CategoryGroupCreate(name=f"{name} Group", is_income=False, sort_order=0),
    )
    return await CategoryService.create(
        db, family_id,
        CategoryCreate(name=name, group_id=group.id, rollover_enabled=rollover),
    )


async def _account(db, family_id):
    return await AccountService.create(
        db, family_id, AccountCreate(name="Checking", type="checking")
    )


async def _spend(db, family_id, account_id, category_id, cents, on=date(2026, 2, 15)):
    """Record spending (negative amount) for a category."""
    await TransactionService.create(
        db, family_id,
        TransactionCreate(
            account_id=account_id,
            date=on,
            amount=cents,  # negative for expense
            category_id=category_id,
        ),
    )


JAN = date(2026, 1, 1)
FEB = date(2026, 2, 1)


# ---------------------------------------------------------------------------
# Month rollover carry
# ---------------------------------------------------------------------------


class TestRolloverCarry:
    @pytest.mark.asyncio
    async def test_positive_leftover_carries_into_next_month(self, db: AsyncSession, family_id):
        """Leftover (allocated - spent) rolls into next month's available."""
        cat = await _make_expense_category(db, family_id, rollover=True)
        account = await _account(db, family_id)

        # Jan: budget $500, spend $350 → $150 leftover
        await AllocationService.set_category_budget(db, family_id, cat.id, JAN, 50000)
        await _spend(db, family_id, account.id, cat.id, -35000, on=date(2026, 1, 15))

        # Feb: budget $200
        await AllocationService.set_category_budget(db, family_id, cat.id, FEB, 20000)

        feb = await AllocationService.get_category_available_amount(
            db, family_id, cat.id, FEB
        )
        assert feb["previous_balance"] == 15000  # Jan leftover carried
        assert feb["available"] == 35000  # 15000 + 20000

    @pytest.mark.asyncio
    async def test_negative_overspend_carries_as_negative(self, db: AsyncSession, family_id):
        """Overspend carries as a negative into next month's available."""
        cat = await _make_expense_category(db, family_id, rollover=True)
        account = await _account(db, family_id)

        # Jan: budget $100, spend $250 → overspent by $150
        await AllocationService.set_category_budget(db, family_id, cat.id, JAN, 10000)
        await _spend(db, family_id, account.id, cat.id, -25000, on=date(2026, 1, 15))

        # Feb: no new budget
        feb = await AllocationService.get_category_available_amount(
            db, family_id, cat.id, FEB
        )
        assert feb["previous_balance"] == -15000  # Jan overspend carried as negative
        assert feb["available"] == -15000

    @pytest.mark.asyncio
    async def test_overspend_does_not_carry_when_rollover_disabled(self, db: AsyncSession, family_id):
        """A non-rollover category starts each month fresh (no negative carry)."""
        cat = await _make_expense_category(db, family_id, rollover=False)
        account = await _account(db, family_id)

        await AllocationService.set_category_budget(db, family_id, cat.id, JAN, 10000)
        await _spend(db, family_id, account.id, cat.id, -25000, on=date(2026, 1, 15))

        feb = await AllocationService.get_category_available_amount(
            db, family_id, cat.id, FEB
        )
        assert feb["previous_balance"] == 0
        assert feb["available"] == 0


# ---------------------------------------------------------------------------
# Cover overspending
# ---------------------------------------------------------------------------


class TestCoverOverspending:
    @pytest.mark.asyncio
    async def test_cover_moves_funds_correctly(self, db: AsyncSession, family_id):
        """Full-deficit cover: overspent category → 0, source drops by the deficit."""
        over = await _make_expense_category(db, family_id, name="Food")
        src = await _make_expense_category(db, family_id, name="Fun")
        account = await _account(db, family_id)

        # Overspent by $100
        await AllocationService.set_category_budget(db, family_id, over.id, FEB, 10000)
        await _spend(db, family_id, account.id, over.id, -20000)
        # Source has $300 available
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)

        result = await AllocationService.cover_overspending(
            db, family_id, FEB,
            overspent_category_id=over.id,
            source_category_id=src.id,
            amount=None,  # default to full deficit
        )

        assert result["amount_moved"] == 10000
        assert result["target"]["available"] == 0
        assert result["source"]["available"] == 20000

        # Re-derive independently to be sure it persisted.
        over_after = await AllocationService.get_category_available_amount(db, family_id, over.id, FEB)
        src_after = await AllocationService.get_category_available_amount(db, family_id, src.id, FEB)
        assert over_after["available"] == 0
        assert src_after["available"] == 20000

    @pytest.mark.asyncio
    async def test_partial_cover(self, db: AsyncSession, family_id):
        """An explicit amount below the deficit is honored; target stays negative."""
        over = await _make_expense_category(db, family_id, name="Food")
        src = await _make_expense_category(db, family_id, name="Fun")
        account = await _account(db, family_id)

        await AllocationService.set_category_budget(db, family_id, over.id, FEB, 10000)
        await _spend(db, family_id, account.id, over.id, -20000)  # deficit $100
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)

        result = await AllocationService.cover_overspending(
            db, family_id, FEB,
            overspent_category_id=over.id,
            source_category_id=src.id,
            amount=4000,  # cover $40 of the $100 deficit
        )
        assert result["amount_moved"] == 4000
        assert result["target"]["available"] == -6000
        assert result["source"]["available"] == 26000

    @pytest.mark.asyncio
    async def test_cannot_over_move_more_than_source_available(self, db: AsyncSession, family_id):
        """The move can't exceed what the source envelope actually holds."""
        over = await _make_expense_category(db, family_id, name="Food")
        src = await _make_expense_category(db, family_id, name="Fun")
        account = await _account(db, family_id)

        await AllocationService.set_category_budget(db, family_id, over.id, FEB, 10000)
        await _spend(db, family_id, account.id, over.id, -20000)  # deficit $100
        # Source only has $50 available — not enough for the full deficit
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 5000)

        with pytest.raises(ValidationError):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=over.id,
                source_category_id=src.id,
                amount=None,  # would need $100, source has $50
            )

        # Nothing moved.
        over_after = await AllocationService.get_category_available_amount(db, family_id, over.id, FEB)
        src_after = await AllocationService.get_category_available_amount(db, family_id, src.id, FEB)
        assert over_after["available"] == -10000
        assert src_after["available"] == 5000

    @pytest.mark.asyncio
    async def test_cannot_over_cover_more_than_deficit(self, db: AsyncSession, family_id):
        """Explicit amount larger than the deficit is rejected."""
        over = await _make_expense_category(db, family_id, name="Food")
        src = await _make_expense_category(db, family_id, name="Fun")
        account = await _account(db, family_id)

        await AllocationService.set_category_budget(db, family_id, over.id, FEB, 10000)
        await _spend(db, family_id, account.id, over.id, -20000)  # deficit $100
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)

        with pytest.raises(ValidationError):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=over.id,
                source_category_id=src.id,
                amount=15000,  # $150 > $100 deficit
            )

    @pytest.mark.asyncio
    async def test_reject_when_target_not_overspent(self, db: AsyncSession, family_id):
        """Covering a category that isn't overspent is a no-op error."""
        target = await _make_expense_category(db, family_id, name="Food")
        src = await _make_expense_category(db, family_id, name="Fun")

        await AllocationService.set_category_budget(db, family_id, target.id, FEB, 10000)
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)

        with pytest.raises(ValidationError):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=target.id,
                source_category_id=src.id,
            )

    @pytest.mark.asyncio
    async def test_reject_same_source_and_target(self, db: AsyncSession, family_id):
        cat = await _make_expense_category(db, family_id, name="Food")
        account = await _account(db, family_id)
        await AllocationService.set_category_budget(db, family_id, cat.id, FEB, 10000)
        await _spend(db, family_id, account.id, cat.id, -20000)

        with pytest.raises(ValidationError):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=cat.id,
                source_category_id=cat.id,
            )

    @pytest.mark.asyncio
    async def test_cover_a_carried_prior_month_overspend(self, db: AsyncSession, family_id):
        """A negative balance carried from a prior month can be covered this month."""
        over = await _make_expense_category(db, family_id, name="Food", rollover=True)
        src = await _make_expense_category(db, family_id, name="Fun")
        account = await _account(db, family_id)

        # Jan overspend of $100 (budget $100, spend $200) → carries -$100 into Feb
        await AllocationService.set_category_budget(db, family_id, over.id, JAN, 10000)
        await _spend(db, family_id, account.id, over.id, -20000, on=date(2026, 1, 15))

        # Feb: source has $300, overspent category has no new budget → available -$100
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)
        feb_before = await AllocationService.get_category_available_amount(db, family_id, over.id, FEB)
        assert feb_before["available"] == -10000

        result = await AllocationService.cover_overspending(
            db, family_id, FEB,
            overspent_category_id=over.id,
            source_category_id=src.id,
        )
        assert result["amount_moved"] == 10000
        assert result["target"]["available"] == 0
        assert result["source"]["available"] == 20000

    @pytest.mark.asyncio
    async def test_family_isolation_source_from_other_family(
        self, db: AsyncSession, family_id, other_family
    ):
        """A source category from another family is invisible → NotFound, no move."""
        over = await _make_expense_category(db, family_id, name="Food")
        account = await _account(db, family_id)
        await AllocationService.set_category_budget(db, family_id, over.id, FEB, 10000)
        await _spend(db, family_id, account.id, over.id, -20000)

        # Foreign source category (belongs to other_family)
        foreign_src = await _make_expense_category(db, other_family.id, name="Foreign")
        await AllocationService.set_category_budget(db, other_family.id, foreign_src.id, FEB, 30000)

        with pytest.raises(NotFoundException):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=over.id,
                source_category_id=foreign_src.id,
            )

        # Overspent category untouched.
        after = await AllocationService.get_category_available_amount(db, family_id, over.id, FEB)
        assert after["available"] == -10000

    @pytest.mark.asyncio
    async def test_family_isolation_target_from_other_family(
        self, db: AsyncSession, family_id, other_family
    ):
        """An overspent target from another family is invisible → NotFound."""
        src = await _make_expense_category(db, family_id, name="Fun")
        await AllocationService.set_category_budget(db, family_id, src.id, FEB, 30000)

        foreign_over = await _make_expense_category(db, other_family.id, name="ForeignFood")

        with pytest.raises(NotFoundException):
            await AllocationService.cover_overspending(
                db, family_id, FEB,
                overspent_category_id=foreign_over.id,
                source_category_id=src.id,
            )
