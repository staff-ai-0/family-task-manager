"""Tests for scripts/restore_plan_prices.py — the remedy that must work on
a REPEAT re-zeroing, unlike `alembic upgrade head` (which only re-asserts
canonical prices the first time the migration runs).

NOTE: conftest builds the schema with Base.metadata.create_all, so
subscription_plans starts EMPTY here. Nothing in this file may assume the
alembic seed ran — rows under test are created explicitly.
"""
import pytest

from app.core.plan_pricing import CANONICAL_PRICES
from app.models.subscription import SubscriptionPlan
from scripts.restore_plan_prices import restore_plan_prices


def _plan(name, currency, monthly, annual, *, active=True, pp_m="P-M", pp_a="P-A"):
    return SubscriptionPlan(
        name=name,
        display_name=name.capitalize(),
        display_name_es=name.capitalize(),
        currency=currency,
        price_monthly_cents=monthly,
        price_annual_cents=annual,
        paypal_plan_id_monthly=pp_m,
        paypal_plan_id_annual=pp_a,
        limits={},
        is_active=active,
        sort_order=10,
    )


@pytest.mark.asyncio
async def test_restores_a_zeroed_row(db_session):
    """The exact production failure: an active paid row re-zeroed out of
    band after the migration already ran once."""
    plan = _plan("plus", "USD", 0, 0)
    db_session.add(plan)
    await db_session.commit()

    changes = await restore_plan_prices(db_session, dry_run=False)
    await db_session.commit()

    assert len(changes) == 1
    assert changes[0]["name"] == "plus"
    assert changes[0]["currency"] == "USD"
    assert changes[0]["old"] == (0, 0)
    assert changes[0]["new"] == CANONICAL_PRICES[("plus", "USD")]

    await db_session.refresh(plan)
    monthly, annual = CANONICAL_PRICES[("plus", "USD")]
    assert plan.price_monthly_cents == monthly
    assert plan.price_annual_cents == annual


@pytest.mark.asyncio
async def test_dry_run_reports_but_does_not_write(db_session):
    plan = _plan("pro", "MXN", 100, 100)
    db_session.add(plan)
    await db_session.commit()

    changes = await restore_plan_prices(db_session, dry_run=True)
    # Deliberately do NOT commit — dry-run must not have mutated the row at
    # all, so a rollback-equivalent check (re-fetch) proves nothing changed.
    await db_session.refresh(plan)

    assert len(changes) == 1
    assert plan.price_monthly_cents == 100
    assert plan.price_annual_cents == 100


@pytest.mark.asyncio
async def test_row_already_canonical_is_not_reported(db_session):
    monthly, annual = CANONICAL_PRICES[("plus", "USD")]
    db_session.add(_plan("plus", "USD", monthly, annual))
    await db_session.commit()

    changes = await restore_plan_prices(db_session, dry_run=False)

    assert changes == []


@pytest.mark.asyncio
async def test_missing_row_is_skipped_not_created(db_session):
    """No (name, currency) pair has a row at all — restore must not
    fabricate one; that is seed/migration territory, not this script's."""
    changes = await restore_plan_prices(db_session, dry_run=False)
    assert changes == []


@pytest.mark.asyncio
async def test_does_not_touch_is_active_or_paypal_plan_ids(db_session):
    """is_active/paypal_plan_id_* are provisioning state owned by
    setup_paypal_plans.py — restore fighting the operator over them is
    exactly how prod's MXN rows ended up active-but-unwired."""
    plan = _plan("plus", "MXN", 0, 0, active=False, pp_m=None, pp_a=None)
    db_session.add(plan)
    await db_session.commit()

    await restore_plan_prices(db_session, dry_run=False)
    await db_session.commit()
    await db_session.refresh(plan)

    monthly, annual = CANONICAL_PRICES[("plus", "MXN")]
    assert plan.price_monthly_cents == monthly
    assert plan.price_annual_cents == annual
    assert plan.is_active is False
    assert plan.paypal_plan_id_monthly is None
    assert plan.paypal_plan_id_annual is None


@pytest.mark.asyncio
async def test_all_four_canonical_rows_restored_in_one_pass(db_session):
    for (name, currency) in CANONICAL_PRICES:
        db_session.add(_plan(name, currency, 1, 1))
    await db_session.commit()

    changes = await restore_plan_prices(db_session, dry_run=False)
    await db_session.commit()

    assert {(c["name"], c["currency"]) for c in changes} == set(CANONICAL_PRICES)
