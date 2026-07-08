"""Tests for the daily subscription_sweep job."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.jobs.subscription_sweep import (
    downgrade_expired_subscriptions,
    reconcile_with_paypal,
)
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


# ---------------------------------------------------------------------------
# PayPal reconciliation pass
# ---------------------------------------------------------------------------


async def _plus_sub(db_session, sample_family, *, status, paypal_id, period_end=None):
    plus = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        price_monthly_cents=500, price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plus)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id, plan_id=plus.id, billing_cycle="monthly",
        status=status, paypal_subscription_id=paypal_id,
        current_period_end=period_end,
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


@pytest.mark.asyncio
async def test_reconcile_restores_active_and_period_end(
    db_session, sample_family
):
    """Local payment_failed + PayPal ACTIVE (missed recovery webhook) →
    converge to active and adopt PayPal's next_billing_time."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="payment_failed", paypal_id="I-RECONCILE-1",
    )
    sub.payment_failure_at = datetime.now(timezone.utc)
    await db_session.commit()

    next_billing = (
        datetime.now(timezone.utc) + timedelta(days=17)
    ).isoformat().replace("+00:00", "Z")
    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-RECONCILE-1",
            "status": "ACTIVE",
            "plan_id": "P-X",
            "next_billing_at": next_billing,
        },
    ):
        changed = await reconcile_with_paypal(db_session)

    assert changed == 1
    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.payment_failure_at is None
    assert sub.current_period_end is not None


@pytest.mark.asyncio
async def test_reconcile_survives_per_sub_failures(db_session, sample_family):
    """One PayPal API failure must not kill the pass (per-sub try/except)."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="active", paypal_id="I-RECONCILE-BOOM",
    )

    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        side_effect=RuntimeError("paypal down"),
    ):
        changed = await reconcile_with_paypal(db_session)

    assert changed == 0
    await db_session.refresh(sub)
    assert sub.status == "active"  # untouched
