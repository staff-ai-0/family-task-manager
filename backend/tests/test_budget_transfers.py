"""TransferService — moves real money between accounts and envelopes.

This service had 16.7% coverage (import lines only) and no direct tests at all,
while owning the paired-ledger write that account transfers depend on. The
defects these tests pin were all reproduced through the public HTTP routes
before being fixed:

* the two legs of a transfer shared no link key, so deleting or editing one leg
  left the other behind and the family's books stopped balancing;
* the category transfer checked ``budgeted_amount`` instead of the envelope's
  available amount, which both manufactured overspend from an already-spent
  envelope and refused to move money a category had genuinely carried over;
* both endpoints wrote into closed months that every other path refuses;
* a transfer into a closed account made money disappear from the budget.

The invariant behind most of these: a transfer moves money, it never creates or
destroys it, so the family's total on-budget balance is unchanged by any
transfer and by any subsequent edit to it.
"""
from datetime import date
from uuid import uuid4

import pytest

from app.schemas.budget import (
    CategoryCreate,
    CategoryGroupCreate,
    TransactionCreate,
)
from app.services.budget.account_service import AccountService
from app.services.budget.allocation_service import AllocationService
from app.services.budget.category_service import CategoryGroupService, CategoryService
from app.services.budget.month_locking_service import MonthLockingService
from app.services.budget.transaction_service import TransactionService
from app.services.budget.transfer_service import TransferService

FEB = date(2026, 2, 1)
FEB_DAY = "2026-02-10"


@pytest.fixture
async def accounts(db, family, account_factory):
    a = await account_factory(family.id, name="Checking")
    b = await account_factory(family.id, name="Savings")
    return a, b


@pytest.fixture
async def envelopes(db, family):
    """Two expense categories, the source pre-funded with 30000 for FEB."""
    group = await CategoryGroupService.create(
        db, family.id, CategoryGroupCreate(name="Gastos", is_income=False)
    )
    fun = await CategoryService.create(
        db, family.id, CategoryCreate(name="Fun", group_id=group.id)
    )
    food = await CategoryService.create(
        db, family.id, CategoryCreate(name="Food", group_id=group.id)
    )
    await AllocationService.set_category_budget(db, family.id, fun.id, FEB, 30000)
    return fun, food


async def _total_on_budget(db, family_id):
    return await AccountService.get_total_on_budget_balance(
        db, family_id, date(2026, 2, 28)
    )


class TestAccountTransfer:
    async def test_creates_a_balanced_linked_pair(self, db, family, accounts):
        a, b = accounts
        before = await _total_on_budget(db, family.id)

        legs = await TransferService.transfer_between_accounts(
            db, family.id, a.id, b.id, 10000, FEB_DAY
        )

        assert len(legs) == 2
        assert sorted(int(t.amount) for t in legs) == [-10000, 10000]
        # Both legs carry the same pair id — the link that lets any later
        # mutation treat the transfer as one unit.
        pair_ids = {t.transfer_pair_id for t in legs}
        assert len(pair_ids) == 1 and None not in pair_ids
        assert await _total_on_budget(db, family.id) == before

    async def test_rejects_non_positive_amount(self, db, family, accounts):
        a, b = accounts
        for bad in (0, -5000):
            with pytest.raises(Exception):
                await TransferService.transfer_between_accounts(
                    db, family.id, a.id, b.id, bad, FEB_DAY
                )

    async def test_rejects_same_account(self, db, family, accounts):
        a, _ = accounts
        with pytest.raises(Exception):
            await TransferService.transfer_between_accounts(
                db, family.id, a.id, a.id, 5000, FEB_DAY
            )

    async def test_rejects_closed_account(self, db, family, account_factory, accounts):
        a, _ = accounts
        closed = await account_factory(family.id, name="Old card", closed=True)
        before = await _total_on_budget(db, family.id)

        with pytest.raises(Exception):
            await TransferService.transfer_between_accounts(
                db, family.id, a.id, closed.id, 10000, FEB_DAY
            )

        assert await _total_on_budget(db, family.id) == before

    async def test_rejects_foreign_account(
        self, db, family, other_family, accounts, account_factory
    ):
        a, _ = accounts
        theirs = await account_factory(other_family.id, name="Theirs")
        with pytest.raises(Exception):
            await TransferService.transfer_between_accounts(
                db, family.id, a.id, theirs.id, 10000, FEB_DAY
            )

    async def test_rejects_malformed_date(self, db, family, accounts):
        a, b = accounts
        with pytest.raises(Exception):
            await TransferService.transfer_between_accounts(
                db, family.id, a.id, b.id, 10000, "02/10/2026"
            )

    async def test_refused_when_month_closed(self, db, family, accounts, envelopes):
        # close_month requires the month to have allocations, hence `envelopes`.
        a, b = accounts
        await MonthLockingService.close_month(db, family.id, FEB)

        with pytest.raises(Exception):
            await TransferService.transfer_between_accounts(
                db, family.id, a.id, b.id, 10000, FEB_DAY
            )


class TestTransferPairIntegrity:
    """A transfer must stay balanced through every later mutation."""

    async def test_deleting_one_leg_takes_the_other_with_it(
        self, db, family, accounts
    ):
        a, b = accounts
        before = await _total_on_budget(db, family.id)
        legs = await TransferService.transfer_between_accounts(
            db, family.id, a.id, b.id, 10000, FEB_DAY
        )
        withdrawal = next(t for t in legs if int(t.amount) < 0)

        await TransactionService.delete_by_id(db, withdrawal.id, family.id)

        # Deleting the withdrawal alone used to leave the deposit live and mint
        # 10000 that was never received.
        assert await _total_on_budget(db, family.id) == before
        for leg in legs:
            await db.refresh(leg)
            assert leg.deleted_at is not None

    async def test_editing_a_leg_amount_is_refused(self, db, family, accounts):
        from app.schemas.budget import TransactionUpdate

        a, b = accounts
        before = await _total_on_budget(db, family.id)
        legs = await TransferService.transfer_between_accounts(
            db, family.id, a.id, b.id, 10000, FEB_DAY
        )

        with pytest.raises(Exception):
            await TransactionService.update(
                db, legs[0].id, family.id, TransactionUpdate(amount=-3000)
            )

        assert await _total_on_budget(db, family.id) == before

    async def test_annotating_a_leg_is_still_allowed(self, db, family, accounts):
        """Only the fields that define the movement are frozen."""
        from app.schemas.budget import TransactionUpdate

        a, b = accounts
        legs = await TransferService.transfer_between_accounts(
            db, family.id, a.id, b.id, 10000, FEB_DAY
        )

        updated = await TransactionService.update(
            db, legs[0].id, family.id, TransactionUpdate(notes="ahorro mensual")
        )

        assert updated.notes == "ahorro mensual"

    async def test_ordinary_transactions_are_unaffected_by_the_cascade(
        self, db, family, accounts
    ):
        """A non-transfer row has no pair and must delete alone."""
        a, _ = accounts
        t1 = await TransactionService.create(
            db, family.id,
            TransactionCreate(account_id=a.id, date=date(2026, 2, 10), amount=-5000),
        )
        t2 = await TransactionService.create(
            db, family.id,
            TransactionCreate(account_id=a.id, date=date(2026, 2, 10), amount=-5000),
        )

        await TransactionService.delete_by_id(db, t1.id, family.id)

        await db.refresh(t2)
        assert t2.deleted_at is None


class TestCategoryTransfer:
    async def test_conserves_total_budgeted(self, db, family, envelopes):
        fun, food = envelopes

        result = await TransferService.transfer_between_categories(
            db, family.id, fun.id, food.id, 10000, "2026-02-01"
        )

        assert result["from_category"]["budgeted"] == 20000
        assert result["to_category"]["budgeted"] == 10000

    async def test_cannot_empty_an_already_spent_envelope(
        self, db, family, accounts, envelopes
    ):
        """Guarding on budgeted let a spent envelope be drained again.

        Fun has 30000 budgeted but 30000 already spent, so available is 0.
        Moving 30000 out manufactured a $300 overspend from nothing.
        """
        a, _ = accounts
        fun, food = envelopes
        await TransactionService.create(
            db, family.id,
            TransactionCreate(
                account_id=a.id, date=date(2026, 2, 5),
                amount=-30000, category_id=fun.id,
            ),
        )
        state = await AllocationService.get_category_available_amount(
            db, family.id, fun.id, FEB
        )
        assert int(state["available"]) == 0

        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, food.id, 30000, "2026-02-01"
            )

    async def test_can_move_money_carried_over_from_a_previous_month(
        self, db, family
    ):
        """Guarding on budgeted also REFUSED legitimate moves.

        A category with rollover and nothing budgeted this month still shows
        available > 0 in the UI, but the old check read budgeted (0) and
        rejected the transfer the user was looking straight at.
        """
        group = await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Gastos", is_income=False)
        )
        fun = await CategoryService.create(
            db, family.id,
            CategoryCreate(name="Fun", group_id=group.id, rollover_enabled=True),
        )
        food = await CategoryService.create(
            db, family.id, CategoryCreate(name="Food", group_id=group.id)
        )
        await AllocationService.set_category_budget(
            db, family.id, fun.id, date(2026, 1, 1), 20000
        )

        state = await AllocationService.get_category_available_amount(
            db, family.id, fun.id, FEB
        )
        assert int(state["available"]) == 20000

        result = await TransferService.transfer_between_categories(
            db, family.id, fun.id, food.id, 20000, "2026-02-01"
        )
        assert result["to_category"]["budgeted"] == 20000

    async def test_rejects_same_category(self, db, family, envelopes):
        fun, _ = envelopes
        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, fun.id, 5000, "2026-02-01"
            )

    async def test_rejects_non_positive_amount(self, db, family, envelopes):
        fun, food = envelopes
        for bad in (0, -5000):
            with pytest.raises(Exception):
                await TransferService.transfer_between_categories(
                    db, family.id, fun.id, food.id, bad, "2026-02-01"
                )

    async def test_rejects_income_categories(self, db, family, envelopes):
        """Ready-to-Assign counts expense budgets only, so an income endpoint
        un-assigns money with no audit trail."""
        fun, _ = envelopes
        income_group = await CategoryGroupService.create(
            db, family.id, CategoryGroupCreate(name="Ingresos", is_income=True)
        )
        salary = await CategoryService.create(
            db, family.id, CategoryCreate(name="Salario", group_id=income_group.id)
        )

        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, salary.id, 10000, "2026-02-01"
            )

    async def test_rejects_foreign_category(self, db, family, other_family, envelopes):
        fun, _ = envelopes
        their_group = await CategoryGroupService.create(
            db, other_family.id, CategoryGroupCreate(name="Suyo", is_income=False)
        )
        theirs = await CategoryService.create(
            db, other_family.id,
            CategoryCreate(name="Theirs", group_id=their_group.id),
        )

        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, theirs.id, 5000, "2026-02-01"
            )

    async def test_refused_when_month_closed(self, db, family, envelopes):
        fun, food = envelopes
        await MonthLockingService.close_month(db, family.id, FEB)

        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, food.id, 10000, "2026-02-01"
            )

    async def test_normalises_month_to_first_of_month(self, db, family, envelopes):
        fun, food = envelopes

        await TransferService.transfer_between_categories(
            db, family.id, fun.id, food.id, 10000, "2026-02-17"
        )

        state = await AllocationService.get_category_available_amount(
            db, family.id, food.id, FEB
        )
        assert int(state["budgeted"]) == 10000

    async def test_unknown_category_is_refused(self, db, family, envelopes):
        fun, _ = envelopes
        with pytest.raises(Exception):
            await TransferService.transfer_between_categories(
                db, family.id, fun.id, uuid4(), 5000, "2026-02-01"
            )


class TestRemovedDuplicateEndpoint:
    async def test_transfer_service_no_longer_ships_cover_overspending(self):
        """The duplicate implementation decided a category was overspent from
        ``budgeted_amount < 0`` — a value that is normally >= 0 — so it refused
        genuinely overspent categories and had zero callers. The real one lives
        on AllocationService and is reached via /api/budget/allocations/."""
        assert not hasattr(TransferService, "cover_overspending")
        assert hasattr(AllocationService, "cover_overspending")
