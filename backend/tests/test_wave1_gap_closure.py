"""
Tests for Wave 1 Budget Gap Closure features:
- Feature 1: Favorite Payees
- Feature 2: Payee Merging
- Feature 3: Schedule End Modes (yearly, weekend behavior, after_n)
"""

import pytest
import pytest_asyncio
from datetime import date, timedelta
from uuid import uuid4

from app.models.budget import (
    BudgetAccount,
    BudgetPayee,
    BudgetRecurringTransaction,
    BudgetTransaction,
)
from app.schemas.budget import PayeeCreate, PayeeUpdate, PayeeMergeRequest
from app.services.budget.payee_service import PayeeService
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.core.exceptions import ValidationException, NotFoundException


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def budget_account(db_session, test_family):
    """Create a budget account for testing."""
    account = BudgetAccount(
        family_id=test_family.id,
        name="Test Checking",
        type="checking",
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)
    return account


@pytest_asyncio.fixture
async def payee_a(db_session, test_family):
    """Create payee A."""
    p = BudgetPayee(family_id=test_family.id, name="Payee A")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def payee_b(db_session, test_family):
    """Create payee B."""
    p = BudgetPayee(family_id=test_family.id, name="Payee B")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest_asyncio.fixture
async def payee_c(db_session, test_family):
    """Create payee C."""
    p = BudgetPayee(family_id=test_family.id, name="Payee C")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ===========================================================================
# FEATURE 1: Favorite Payees
# ===========================================================================

class TestFavoritePayees:

    @pytest.mark.asyncio
    async def test_create_payee_with_favorite(self, db_session, test_family):
        """Create a payee explicitly marked as favorite."""
        data = PayeeCreate(name="Fav Payee", is_favorite=True)
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is True

    @pytest.mark.asyncio
    async def test_create_payee_default_not_favorite(self, db_session, test_family):
        """Default is_favorite should be False."""
        data = PayeeCreate(name="Normal Payee")
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is False

    @pytest.mark.asyncio
    async def test_update_payee_toggle_favorite(self, db_session, test_family):
        """Toggle is_favorite via update."""
        data = PayeeCreate(name="Toggle Payee")
        payee = await PayeeService.create(db_session, test_family.id, data)
        assert payee.is_favorite is False

        updated = await PayeeService.update(
            db_session, payee.id, test_family.id, PayeeUpdate(is_favorite=True)
        )
        assert updated.is_favorite is True

    @pytest.mark.asyncio
    async def test_list_favorites_only(self, db_session, test_family):
        """list_by_family_filtered with favorites_only returns only favorites."""
        await PayeeService.create(
            db_session, test_family.id, PayeeCreate(name="Fav", is_favorite=True)
        )
        await PayeeService.create(
            db_session, test_family.id, PayeeCreate(name="Normal")
        )

        favs = await PayeeService.list_by_family_filtered(
            db_session, test_family.id, favorites_only=True
        )
        assert len(favs) == 1
        assert favs[0].name == "Fav"

    @pytest.mark.asyncio
    async def test_list_all_payees(self, db_session, test_family):
        """list_by_family_filtered without filter returns all."""
        await PayeeService.create(
            db_session, test_family.id, PayeeCreate(name="A", is_favorite=True)
        )
        await PayeeService.create(
            db_session, test_family.id, PayeeCreate(name="B")
        )

        all_payees = await PayeeService.list_by_family_filtered(
            db_session, test_family.id, favorites_only=False
        )
        assert len(all_payees) == 2


# ===========================================================================
# FEATURE 2: Payee Merging
# ===========================================================================

class TestPayeeMerging:

    @pytest.mark.asyncio
    async def test_merge_updates_transactions(
        self, db_session, test_family, budget_account, payee_a, payee_b
    ):
        """After merge, transactions from source point to target."""
        # Create transactions with payee_b (source)
        tx = BudgetTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            date=date.today(),
            amount=-5000,
            payee_id=payee_b.id,
        )
        db_session.add(tx)
        await db_session.commit()
        await db_session.refresh(tx)

        # Merge payee_b into payee_a
        merge_data = PayeeMergeRequest(target_id=payee_a.id, source_ids=[payee_b.id])
        result = await PayeeService.merge(db_session, test_family.id, merge_data)
        assert result.id == payee_a.id

        await db_session.refresh(tx)
        assert tx.payee_id == payee_a.id

    @pytest.mark.asyncio
    async def test_merge_deletes_sources(
        self, db_session, test_family, payee_a, payee_b, payee_c
    ):
        """Source payees are deleted after merge."""
        merge_data = PayeeMergeRequest(
            target_id=payee_a.id, source_ids=[payee_b.id, payee_c.id]
        )
        await PayeeService.merge(db_session, test_family.id, merge_data)

        with pytest.raises(NotFoundException):
            await PayeeService.get_by_id(db_session, payee_b.id, test_family.id)
        with pytest.raises(NotFoundException):
            await PayeeService.get_by_id(db_session, payee_c.id, test_family.id)

    @pytest.mark.asyncio
    async def test_merge_target_in_sources_raises(
        self, db_session, test_family, payee_a
    ):
        """target_id in source_ids must raise ValidationException."""
        merge_data = PayeeMergeRequest(
            target_id=payee_a.id, source_ids=[payee_a.id]
        )
        with pytest.raises(ValidationException):
            await PayeeService.merge(db_session, test_family.id, merge_data)

    @pytest.mark.asyncio
    async def test_merge_updates_recurring_transactions(
        self, db_session, test_family, budget_account, payee_a, payee_b
    ):
        """Recurring transactions are reassigned from source to target."""
        rt = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            payee_id=payee_b.id,
            name="Monthly Bill",
            amount=-10000,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date.today(),
        )
        db_session.add(rt)
        await db_session.commit()
        await db_session.refresh(rt)

        merge_data = PayeeMergeRequest(target_id=payee_a.id, source_ids=[payee_b.id])
        await PayeeService.merge(db_session, test_family.id, merge_data)

        await db_session.refresh(rt)
        assert rt.payee_id == payee_a.id


# ===========================================================================
# FEATURE 3: Schedule End Modes
# ===========================================================================

class TestScheduleEndModes:

    # --- Yearly recurrence ---

    def test_yearly_recurrence(self):
        """Yearly recurrence type calculates next year."""
        start = date(2025, 3, 15)
        from_date = date(2025, 3, 16)
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="yearly",
            recurrence_interval=1,
            recurrence_pattern=None,
            end_date=None,
            from_date=from_date,
        )
        assert next_d == date(2026, 3, 15)

    def test_every_two_years(self):
        """Yearly with interval=2 skips a year."""
        start = date(2024, 6, 1)
        from_date = date(2026, 6, 2)  # just past the 2026 occurrence
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="yearly",
            recurrence_interval=2,
            recurrence_pattern=None,
            end_date=None,
            from_date=from_date,
        )
        assert next_d == date(2028, 6, 1)

    # --- after_n exhausted ---

    def test_after_n_exhausted_returns_none(self):
        """When occurrence_count >= occurrence_limit, returns None."""
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2025, 1, 1),
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 1},
            end_date=None,
            from_date=date(2025, 6, 1),
            end_mode="after_n",
            occurrence_limit=5,
            occurrence_count=5,
        )
        assert next_d is None

    def test_after_n_under_limit(self):
        """When occurrence_count < occurrence_limit, returns a date."""
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=date(2025, 1, 1),
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 1},
            end_date=None,
            from_date=date(2025, 3, 1),
            end_mode="after_n",
            occurrence_limit=5,
            occurrence_count=2,
        )
        assert next_d is not None
        assert next_d == date(2025, 4, 1)

    # --- Weekend behavior ---

    def test_weekend_before_saturday(self):
        """Saturday shifted to Friday with weekend_behavior='before'."""
        # 2026-04-04 is a Saturday
        start = date(2026, 3, 1)
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 4},
            end_date=None,
            from_date=date(2026, 3, 5),
            weekend_behavior="before",
        )
        assert next_d == date(2026, 4, 3)  # Friday

    def test_weekend_after_saturday(self):
        """Saturday shifted to Monday with weekend_behavior='after'."""
        # 2026-04-04 is a Saturday
        start = date(2026, 3, 1)
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 4},
            end_date=None,
            from_date=date(2026, 3, 5),
            weekend_behavior="after",
        )
        assert next_d == date(2026, 4, 6)  # Monday

    def test_weekend_none_no_shift(self):
        """No shift with weekend_behavior='none'."""
        # 2026-04-04 is a Saturday
        start = date(2026, 3, 1)
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 4},
            end_date=None,
            from_date=date(2026, 3, 5),
            weekend_behavior="none",
        )
        assert next_d == date(2026, 4, 4)  # Saturday stays

    def test_weekday_unaffected_by_weekend_behavior(self):
        """Weekday dates are not shifted regardless of weekend_behavior."""
        # 2026-04-06 is a Monday
        start = date(2026, 3, 1)
        next_d = RecurringTransactionService._calculate_next_occurrence(
            start_date=start,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            recurrence_pattern={"day": 6},
            end_date=None,
            from_date=date(2026, 3, 7),
            weekend_behavior="before",
        )
        assert next_d == date(2026, 4, 6)  # Monday, no shift

    # --- post_transaction ---

    @pytest.mark.asyncio
    async def test_post_increments_occurrence_count(
        self, db_session, test_family, budget_account
    ):
        """Posting a transaction increments occurrence_count."""
        rt = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            name="Monthly Sub",
            amount=-1500,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date(2025, 1, 1),
            next_due_date=date(2025, 1, 1),
            end_mode="never",
            occurrence_count=0,
        )
        db_session.add(rt)
        await db_session.commit()
        await db_session.refresh(rt)

        await RecurringTransactionService.post_transaction(
            db_session, rt.id, test_family.id, transaction_date=date(2025, 1, 1)
        )
        await db_session.refresh(rt)
        assert rt.occurrence_count == 1

    @pytest.mark.asyncio
    async def test_post_deactivates_at_limit(
        self, db_session, test_family, budget_account
    ):
        """Posting the last allowed transaction deactivates the schedule."""
        rt = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            name="Limited Sub",
            amount=-2000,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date(2025, 1, 1),
            next_due_date=date(2025, 3, 1),
            end_mode="after_n",
            occurrence_limit=3,
            occurrence_count=2,  # one more allowed
        )
        db_session.add(rt)
        await db_session.commit()
        await db_session.refresh(rt)

        await RecurringTransactionService.post_transaction(
            db_session, rt.id, test_family.id, transaction_date=date(2025, 3, 1)
        )
        await db_session.refresh(rt)
        assert rt.occurrence_count == 3
        assert rt.is_active is False
        assert rt.next_due_date is None

    # --- Bug fix: post_transaction uses correct field names ---

    @pytest.mark.asyncio
    async def test_post_transaction_creates_valid_transaction(
        self, db_session, test_family, budget_account
    ):
        """post_transaction creates a BudgetTransaction with correct fields (date, notes)."""
        rt = BudgetRecurringTransaction(
            family_id=test_family.id,
            account_id=budget_account.id,
            name="Rent",
            description="Monthly rent payment",
            amount=-100000,
            recurrence_type="monthly_dayofmonth",
            recurrence_interval=1,
            start_date=date(2025, 1, 1),
            next_due_date=date(2025, 1, 1),
        )
        db_session.add(rt)
        await db_session.commit()
        await db_session.refresh(rt)

        tx = await RecurringTransactionService.post_transaction(
            db_session, rt.id, test_family.id, transaction_date=date(2025, 1, 1)
        )
        assert tx.date == date(2025, 1, 1)
        assert tx.notes == "Monthly rent payment"
        assert tx.amount == -100000
        assert tx.account_id == budget_account.id

    # --- _adjust_weekend static method ---

    def test_adjust_weekend_sunday_before(self):
        """Sunday shifted to Friday with 'before'."""
        # 2026-04-05 is a Sunday
        result = RecurringTransactionService._adjust_weekend(date(2026, 4, 5), "before")
        assert result == date(2026, 4, 3)  # Friday

    def test_adjust_weekend_sunday_after(self):
        """Sunday shifted to Monday with 'after'."""
        result = RecurringTransactionService._adjust_weekend(date(2026, 4, 5), "after")
        assert result == date(2026, 4, 6)  # Monday
