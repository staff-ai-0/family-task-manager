"""Tests for the daily subscription_sweep job."""
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs.subscription_sweep import downgrade_expired_subscriptions
from app.models.subscription import FamilySubscription, SubscriptionPlan


@pytest.mark.asyncio
async def test_sweep_downgrades_expired_cancel_at_period_end(
    db_session, sample_family
):
    free = SubscriptionPlan(
        name="free", display_name="Free", display_name_es="Gratis",
        price_monthly_cents=0, price_annual_cents=0,
        limits={"max_family_members": 4},
    )
    plus = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        price_monthly_cents=500, price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add_all([free, plus])
    await db_session.commit()

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    sub = FamilySubscription(
        family_id=sample_family.id, plan_id=plus.id, billing_cycle="monthly",
        status="active", paypal_subscription_id="I-EXPIRED",
        cancel_at_period_end=True, current_period_end=yesterday,
    )
    db_session.add(sub)
    await db_session.commit()

    downgraded = await downgrade_expired_subscriptions(db_session)
    assert downgraded == 1
    await db_session.refresh(sub)
    assert sub.status == "cancelled"


@pytest.mark.asyncio
async def test_sweep_skips_active_unflagged(db_session, sample_family):
    plus = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        price_monthly_cents=500, price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plus)
    await db_session.commit()

    future = datetime.now(timezone.utc) + timedelta(days=10)
    sub = FamilySubscription(
        family_id=sample_family.id, plan_id=plus.id, billing_cycle="monthly",
        status="active", paypal_subscription_id="I-LIVE",
        cancel_at_period_end=False, current_period_end=future,
    )
    db_session.add(sub)
    await db_session.commit()

    downgraded = await downgrade_expired_subscriptions(db_session)
    assert downgraded == 0
    await db_session.refresh(sub)
    assert sub.status == "active"
