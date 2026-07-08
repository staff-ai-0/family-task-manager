"""Tests for subscription_state pure transition logic."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.services.subscription_state import (
    apply_activated,
    apply_cancelled,
    apply_payment_completed,
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


# ---------------------------------------------------------------------------
# PAYMENT.SALE.COMPLETED period-advance idempotency (whole-PR review, MAJOR 1)
# ---------------------------------------------------------------------------


async def _make_active_sub(db, family, *, paypal_id, period_end):
    plan = await _make_plan(db, "plus")
    sub = FamilySubscription(
        family_id=family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id=paypal_id,
        current_period_end=period_end,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


def _aware_end(sub):
    end = sub.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end


@pytest.mark.asyncio
async def test_payment_completed_initial_charge_does_not_double_advance(
    db_session, sample_family
):
    """Regression: the PAYMENT.SALE.COMPLETED for the INITIAL activation
    charge must NOT advance current_period_end again — activation already set
    it one full cycle out."""
    activation_end = datetime.now(timezone.utc) + timedelta(days=30)
    sub = await _make_active_sub(
        db_session, sample_family,
        paypal_id="I-INITIAL-SALE", period_end=activation_end,
    )

    result = await apply_payment_completed(db_session, "I-INITIAL-SALE")
    assert result is not None
    await db_session.refresh(sub)
    assert abs((_aware_end(sub) - activation_end).total_seconds()) < 1
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_payment_completed_renewal_advance_is_idempotent(
    db_session, sample_family
):
    """A replayed renewal sale event must not advance the period twice: the
    first apply (near period end) advances one cycle, the second is a no-op
    because the new period end is now far in the future."""
    old_end = datetime.now(timezone.utc) + timedelta(hours=1)
    sub = await _make_active_sub(
        db_session, sample_family,
        paypal_id="I-RENEW-REPLAY", period_end=old_end,
    )

    await apply_payment_completed(db_session, "I-RENEW-REPLAY")
    await db_session.refresh(sub)
    end_after_first = _aware_end(sub)
    assert end_after_first > old_end + timedelta(days=29)

    await apply_payment_completed(db_session, "I-RENEW-REPLAY")
    await db_session.refresh(sub)
    assert _aware_end(sub) == end_after_first


@pytest.mark.asyncio
async def test_payment_completed_late_renewal_still_advances(
    db_session, sample_family
):
    """A renewal sale landing after the period already lapsed (late webhook)
    still advances the period from now."""
    old_end = datetime.now(timezone.utc) - timedelta(days=1)
    sub = await _make_active_sub(
        db_session, sample_family,
        paypal_id="I-RENEW-LATE", period_end=old_end,
    )

    await apply_payment_completed(db_session, "I-RENEW-LATE")
    await db_session.refresh(sub)
    assert _aware_end(sub) > datetime.now(timezone.utc) + timedelta(days=29)


@pytest.mark.asyncio
async def test_payment_completed_explicit_period_end_bypasses_window_guard(
    db_session, sample_family
):
    """An authoritative period_end from the caller (PayPal's own
    next_billing_time) is adopted even mid-cycle — forward-only."""
    old_end = datetime.now(timezone.utc) + timedelta(days=30)
    sub = await _make_active_sub(
        db_session, sample_family,
        paypal_id="I-AUTHORITATIVE", period_end=old_end,
    )

    authoritative = datetime.now(timezone.utc) + timedelta(days=45)
    await apply_payment_completed(
        db_session, "I-AUTHORITATIVE", period_end=authoritative
    )
    await db_session.refresh(sub)
    assert abs((_aware_end(sub) - authoritative).total_seconds()) < 1


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
