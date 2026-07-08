"""Tests for subscription_state pure transition logic."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.services.subscription_state import (
    apply_activated,
    apply_cancelled,
    apply_payment_failed,
)


@pytest.fixture(autouse=True)
def _mute_email_transport():
    """State transitions dispatch billing emails; never hit SMTP in tests."""
    with patch(
        "app.services.email_service.EmailService._send",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.mark.asyncio
async def test_apply_activated_sets_active_status(db_session, sample_family):
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="pending",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_activated(
        db_session,
        paypal_subscription_id="I-ABC",
        period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )

    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.current_period_end is not None


@pytest.mark.asyncio
async def test_apply_cancelled_sets_flag_only(db_session, sample_family):
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_cancelled(db_session, paypal_subscription_id="I-ABC")

    await db_session.refresh(sub)
    assert sub.cancel_at_period_end is True
    assert sub.status == "active"  # NOT immediately cancelled


@pytest.mark.asyncio
async def test_apply_payment_failed_sets_timestamp(db_session, sample_family):
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_payment_failed(db_session, paypal_subscription_id="I-ABC")

    await db_session.refresh(sub)
    assert sub.status == "payment_failed"
    assert sub.payment_failure_at is not None


@pytest.mark.asyncio
async def test_apply_activated_idempotent(db_session, sample_family):
    """Reapplying ACTIVATED twice is a no-op."""
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="pending",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    end = datetime.now(timezone.utc) + timedelta(days=30)
    await apply_activated(db_session, "I-ABC", end)
    first_status = sub.status
    await apply_activated(db_session, "I-ABC", end)
    await db_session.refresh(sub)
    assert sub.status == first_status == "active"


@pytest.mark.asyncio
async def test_apply_payment_failed_idempotent_preserves_timestamp(
    db_session, sample_family
):
    """Second PAYMENT.FAILED in dunning cycle must NOT reset the timestamp."""
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_payment_failed(db_session, "I-ABC")
    await db_session.refresh(sub)
    first_failure = sub.payment_failure_at
    assert first_failure is not None

    # Sleep tick then re-apply
    import asyncio
    await asyncio.sleep(0.01)
    await apply_payment_failed(db_session, "I-ABC")
    await db_session.refresh(sub)
    assert sub.payment_failure_at == first_failure


@pytest.mark.asyncio
async def test_apply_cancelled_idempotent(db_session, sample_family):
    """Second CANCELLED must not change cancelled_at."""
    plan = await _make_plan(db_session, "plus")
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-ABC",
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_cancelled(db_session, "I-ABC")
    await db_session.refresh(sub)
    first_cancel = sub.cancelled_at

    import asyncio
    await asyncio.sleep(0.01)
    await apply_cancelled(db_session, "I-ABC")
    await db_session.refresh(sub)
    assert sub.cancelled_at == first_cancel


@pytest.mark.asyncio
async def test_apply_activated_on_missing_sub_returns_none(db_session):
    """Webhook arriving before pending row exists — graceful no-op."""
    from datetime import datetime, timedelta, timezone
    result = await apply_activated(
        db_session,
        paypal_subscription_id="I-DOES-NOT-EXIST",
        period_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    assert result is None


@pytest.mark.asyncio
async def test_apply_activated_does_not_wipe_trial_end_at(
    db_session, sample_family
):
    """Re-applying ACTIVATED with trial_end_at=None must preserve existing value."""
    plan = await _make_plan(db_session, "plus")
    original_trial_end = datetime.now(timezone.utc) + timedelta(days=7)
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="pending",
        paypal_subscription_id="I-ABC",
        trial_end_at=original_trial_end,
    )
    db_session.add(sub)
    await db_session.commit()

    await apply_activated(
        db_session,
        paypal_subscription_id="I-ABC",
        period_end=datetime.now(timezone.utc) + timedelta(days=30),
        trial_end_at=None,  # caller didn't supply
    )
    await db_session.refresh(sub)
    # trial_end_at survived
    assert sub.trial_end_at == original_trial_end


async def _make_plan(db, name):
    plan = SubscriptionPlan(
        name=name,
        display_name=name.capitalize(),
        display_name_es=name.capitalize(),
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6, "budget_reports": True},
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan
