"""
Tests for ReportService.get_cash_flow_forecast (P2 — bill calendar + cash-flow forecast).

Covers:
- Projection math: scheduled income/bills over the horizon, projected running balance.
- Empty case: no accounts / no recurring templates.
- Horizon boundary: occurrences beyond the window are excluded.
- Already-posted occurrences (last_generated_date) are not double-counted.
- Tenant isolation: one family's templates/accounts never leak into another's forecast.
"""

import pytest
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.family import Family
from app.services.budget.report_service import ReportService
from app.services.budget.account_service import AccountService
from app.services.budget.recurring_transaction_service import RecurringTransactionService
from app.schemas.budget import AccountCreate, RecurringTransactionCreate


async def _daily_template(db, family_id, account_id, *, name, amount, start_date):
    """Create an active daily recurring template (interval 1)."""
    return await RecurringTransactionService.create(
        db, family_id,
        RecurringTransactionCreate(
            account_id=account_id,
            name=name,
            amount=amount,
            recurrence_type="daily",
            recurrence_interval=1,
            recurrence_pattern=None,
            start_date=start_date,
            is_active=True,
        ),
    )


class TestCashFlowForecastMath:
    """Projection math: income and bills projected across the horizon."""

    @pytest.mark.asyncio
    async def test_income_and_bills_projected_over_horizon(
        self, db: AsyncSession, family_id
    ):
        today = date.today()
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=100_000),
        )

        # Both start tomorrow so day 0 has no occurrence (clean anchor point).
        tomorrow = today + timedelta(days=1)
        await _daily_template(
            db, family_id, account.id, name="Allowance",
            amount=500, start_date=tomorrow,  # +$5/day income
        )
        await _daily_template(
            db, family_id, account.id, name="Coffee",
            amount=-1_000, start_date=tomorrow,  # -$10/day bill
        )

        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=5, as_of_date=today
        )

        # 5 daily occurrences of each within (today, today+5].
        assert result["starting_balance"] == 100_000
        assert result["scheduled_income"] == 5 * 500       # 2_500
        assert result["scheduled_expense"] == 5 * 1_000     # 5_000
        assert result["projected_balance"] == 100_000 + 2_500 - 5_000  # 97_500
        assert result["currency"] == "MXN"
        assert result["horizon_days"] == 5

        # 5 income + 5 expense occurrences on the calendar.
        assert len(result["upcoming"]) == 10
        # Each upcoming item carries a signed amount + is_income flag + account.
        for item in result["upcoming"]:
            assert item["account_name"] == "Checking"
            assert item["is_income"] == (item["amount"] >= 0)

        # Running-balance series: anchored at the current balance, ends at horizon.
        series = result["series"]
        assert series[0]["balance"] == 100_000
        assert series[-1]["date"] == (today + timedelta(days=5)).isoformat()
        assert series[-1]["balance"] == 97_500

        # Per-account row mirrors the totals for the single account.
        assert len(result["accounts"]) == 1
        acct_row = result["accounts"][0]
        assert acct_row["starting_balance"] == 100_000
        assert acct_row["scheduled_income"] == 2_500
        assert acct_row["scheduled_expense"] == 5_000
        assert acct_row["projected_balance"] == 97_500

    @pytest.mark.asyncio
    async def test_cents_fields_are_int(self, db: AsyncSession, family_id):
        """cents fields must serialize as ints (strict-Int mobile decoders)."""
        from decimal import Decimal

        today = date.today()
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Chk", type="checking", starting_balance=50_000),
        )
        await _daily_template(
            db, family_id, account.id, name="Bill",
            amount=-2_000, start_date=today + timedelta(days=1),
        )

        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=10, as_of_date=today
        )

        for key in ("starting_balance", "scheduled_income", "scheduled_expense",
                    "projected_balance", "projected_low"):
            assert isinstance(result[key], int), f"{key} must be int"
            assert not isinstance(result[key], Decimal)
        for item in result["upcoming"]:
            assert isinstance(item["amount"], int)
        for pt in result["series"]:
            assert isinstance(pt["balance"], int)

    @pytest.mark.asyncio
    async def test_projected_low_reflects_dip(self, db: AsyncSession, family_id):
        """projected_low is the lowest point the running balance reaches."""
        today = date.today()
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=30_000),
        )
        # -$100/day bill, no income → balance only falls.
        await _daily_template(
            db, family_id, account.id, name="Rent bit",
            amount=-10_000, start_date=today + timedelta(days=1),
        )
        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=5, as_of_date=today
        )
        # 5 x -$100 = -$500 → ends (and bottoms) at 30_000 - 50_000 = -20_000.
        assert result["projected_balance"] == -20_000
        assert result["projected_low"] == -20_000


class TestCashFlowForecastEmpty:
    """Empty / no-data cases."""

    @pytest.mark.asyncio
    async def test_no_accounts_returns_zeros(self, db: AsyncSession, family_id):
        today = date.today()
        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=30, as_of_date=today
        )
        assert result["starting_balance"] == 0
        assert result["projected_balance"] == 0
        assert result["accounts"] == []
        assert result["upcoming"] == []
        # Series still anchors both endpoints of the horizon.
        assert len(result["series"]) == 2
        assert result["series"][0]["date"] == today.isoformat()
        assert result["series"][-1]["date"] == (today + timedelta(days=30)).isoformat()

    @pytest.mark.asyncio
    async def test_accounts_no_templates(self, db: AsyncSession, family_id):
        today = date.today()
        await AccountService.create(
            db, family_id,
            AccountCreate(name="Savings", type="savings", starting_balance=75_000),
        )
        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=30, as_of_date=today
        )
        assert result["starting_balance"] == 75_000
        assert result["projected_balance"] == 75_000
        assert result["upcoming"] == []
        assert result["series"][0]["balance"] == 75_000
        assert result["series"][-1]["balance"] == 75_000


class TestCashFlowForecastHorizon:
    """Horizon boundary + already-posted handling."""

    @pytest.mark.asyncio
    async def test_occurrences_beyond_horizon_excluded(
        self, db: AsyncSession, family_id
    ):
        today = date.today()
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=20_000),
        )
        # Starts 40 days out — nothing lands inside a 30-day window.
        await _daily_template(
            db, family_id, account.id, name="Future bill",
            amount=-5_000, start_date=today + timedelta(days=40),
        )
        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=30, as_of_date=today
        )
        assert result["upcoming"] == []
        assert result["projected_balance"] == 20_000

    @pytest.mark.asyncio
    async def test_already_posted_occurrences_not_double_counted(
        self, db: AsyncSession, family_id
    ):
        """Occurrences on/before last_generated_date are skipped."""
        today = date.today()
        account = await AccountService.create(
            db, family_id,
            AccountCreate(name="Checking", type="checking", starting_balance=100_000),
        )
        tmpl = await _daily_template(
            db, family_id, account.id, name="Daily bill",
            amount=-1_000, start_date=today,
        )
        # Pretend it already posted through today+3.
        tmpl.last_generated_date = today + timedelta(days=3)
        await db.commit()

        result = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=10, as_of_date=today
        )
        # Only today+4 .. today+10 remain = 7 occurrences.
        assert len(result["upcoming"]) == 7
        assert result["scheduled_expense"] == 7 * 1_000
        for item in result["upcoming"]:
            assert item["date"] > (today + timedelta(days=3)).isoformat()


class TestCashFlowForecastIsolation:
    """Multi-tenant isolation — no cross-family leakage."""

    @pytest.mark.asyncio
    async def test_other_family_data_excluded(self, db: AsyncSession, family_id):
        today = date.today()

        # Family A (family_id fixture): one account + one template.
        acct_a = await AccountService.create(
            db, family_id,
            AccountCreate(name="A Checking", type="checking", starting_balance=10_000),
        )
        await _daily_template(
            db, family_id, acct_a.id, name="A Bill",
            amount=-1_000, start_date=today + timedelta(days=1),
        )

        # Family B: separate family, account, and template.
        fam_b = Family(name="Family B")
        db.add(fam_b)
        await db.commit()
        await db.refresh(fam_b)

        acct_b = await AccountService.create(
            db, fam_b.id,
            AccountCreate(name="B Checking", type="checking", starting_balance=999_999),
        )
        await _daily_template(
            db, fam_b.id, acct_b.id, name="B Bill",
            amount=-7_000, start_date=today + timedelta(days=1),
        )

        # Family A's forecast sees only its own account + template.
        result_a = await ReportService.get_cash_flow_forecast(
            db, family_id, horizon_days=5, as_of_date=today
        )
        assert result_a["starting_balance"] == 10_000
        acct_names_a = {a["account_name"] for a in result_a["accounts"]}
        assert acct_names_a == {"A Checking"}
        upcoming_names_a = {i["name"] for i in result_a["upcoming"]}
        assert upcoming_names_a == {"A Bill"}
        assert result_a["scheduled_expense"] == 5 * 1_000

        # Family B's forecast sees only its own.
        result_b = await ReportService.get_cash_flow_forecast(
            db, fam_b.id, horizon_days=5, as_of_date=today
        )
        assert result_b["starting_balance"] == 999_999
        assert {a["account_name"] for a in result_b["accounts"]} == {"B Checking"}
        assert {i["name"] for i in result_b["upcoming"]} == {"B Bill"}
