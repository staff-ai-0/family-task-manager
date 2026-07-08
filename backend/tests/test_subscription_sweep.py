"""Tests for the daily subscription_sweep job."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.jobs.subscription_sweep import (
    downgrade_expired_subscriptions,
    downgrade_grace_expired_subscriptions,
    reconcile_with_paypal,
)
from app.models.subscription import FamilySubscription, SubscriptionPlan


@pytest.fixture(autouse=True)
def _mute_email_transport():
    """Sweep passes dispatch billing emails; never hit SMTP in tests."""
    with patch(
        "app.services.email_service.EmailService._send",
        new=AsyncMock(return_value=True),
    ):
        yield


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


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_reconcile_restores_stranded_pending(db_session, sample_family):
    """Regression (whole-PR review, MAJOR 4): a 'pending' row whose ACTIVATED
    webhook was missed (buyer approved but never returned to /activate) must
    be reconciled to active — that stranding is exactly what the pass exists
    to fix."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="pending", paypal_id="I-STRANDED-PENDING",
    )

    next_billing = _iso_z(datetime.now(timezone.utc) + timedelta(days=30))
    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-STRANDED-PENDING",
            "status": "ACTIVE",
            "plan_id": "P-X",
            "next_billing_at": next_billing,
        },
    ):
        changed = await reconcile_with_paypal(db_session)

    assert changed == 1
    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.current_period_end is not None
    assert sub.current_period_start is not None


@pytest.mark.asyncio
async def test_reconcile_recovers_grace_expired_with_newer_payment(
    db_session, sample_family
):
    """Regression (whole-PR review, MAJOR 4): a grace_expired row whose
    recovery charge (PAYMENT.SALE.COMPLETED) webhook was missed is restored
    when PayPal reports a next_billing_time newer than our failure marker."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="grace_expired", paypal_id="I-GRACE-RECOVERED",
    )
    sub.payment_failure_at = datetime.now(timezone.utc) - timedelta(days=12)
    await db_session.commit()

    next_billing = _iso_z(datetime.now(timezone.utc) + timedelta(days=25))
    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-GRACE-RECOVERED",
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


@pytest.mark.asyncio
async def test_reconcile_leaves_grace_running_mid_retry(
    db_session, sample_family
):
    """PayPal keeps a sub ACTIVE while retrying a failed payment itself —
    that is NOT a recovery. Without a payment newer than our failure marker
    the dunning state (and its grace clock) must stay untouched."""
    failure_at = datetime.now(timezone.utc) - timedelta(days=2)
    sub = await _plus_sub(
        db_session, sample_family,
        status="payment_failed", paypal_id="I-MID-RETRY",
        period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )
    sub.payment_failure_at = failure_at
    await db_session.commit()

    # next_billing_time still points at the outstanding (failed) billing
    # date — i.e. NOT newer than the failure.
    stale_billing = _iso_z(failure_at - timedelta(days=1))
    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-MID-RETRY",
            "status": "ACTIVE",
            "plan_id": "P-X",
            "next_billing_at": stale_billing,
        },
    ):
        changed = await reconcile_with_paypal(db_session)

    assert changed == 0
    await db_session.refresh(sub)
    assert sub.status == "payment_failed"
    failure_after = sub.payment_failure_at
    if failure_after.tzinfo is None:
        failure_after = failure_after.replace(tzinfo=timezone.utc)
    assert failure_after == failure_at  # grace clock untouched


@pytest.mark.asyncio
async def test_reconcile_suspended_does_not_resurrect_grace_expired(
    db_session, sample_family
):
    """grace_expired + PayPal SUSPENDED are already converged (downgraded,
    not billing). Re-stamping payment_failed would flip-flop with the
    grace-expiry pass every night."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="grace_expired", paypal_id="I-GRACE-SUSPENDED",
    )
    sub.payment_failure_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-GRACE-SUSPENDED",
            "status": "SUSPENDED",
            "plan_id": "P-X",
            "next_billing_at": None,
        },
    ):
        changed = await reconcile_with_paypal(db_session)

    assert changed == 0
    await db_session.refresh(sub)
    assert sub.status == "grace_expired"


@pytest.mark.asyncio
async def test_reconcile_ages_out_stale_pending(db_session, sample_family):
    """Regression (re-review, NIT): an abandoned checkout (pending, untouched
    for >7 days — PayPal APPROVAL_PENDING forever) must age out of the
    reconciliation pass instead of being polled against the PayPal API every
    night indefinitely."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="pending", paypal_id="I-ABANDONED-PENDING",
    )
    # Explicit assignment wins over the onupdate default.
    sub.updated_at = datetime.now(timezone.utc) - timedelta(days=8)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
    ) as mock_get:
        changed = await reconcile_with_paypal(db_session)

    assert changed == 0
    mock_get.assert_not_called()
    await db_session.refresh(sub)
    assert sub.status == "pending"


@pytest.mark.asyncio
async def test_reconcile_ages_out_stale_grace_expired(db_session, sample_family):
    """Regression (re-review, NIT): a grace_expired row whose PayPal side sits
    SUSPENDED forever must stop being reconciled once well past any realistic
    PayPal retry window (>60 days since the downgrade)."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="grace_expired", paypal_id="I-LONG-DEAD-GRACE",
    )
    sub.payment_failure_at = datetime.now(timezone.utc) - timedelta(days=75)
    sub.updated_at = datetime.now(timezone.utc) - timedelta(days=61)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
    ) as mock_get:
        changed = await reconcile_with_paypal(db_session)

    assert changed == 0
    mock_get.assert_not_called()
    await db_session.refresh(sub)
    assert sub.status == "grace_expired"


@pytest.mark.asyncio
async def test_reconcile_keeps_polling_active_rows_regardless_of_age(
    db_session, sample_family
):
    """The age cap applies ONLY to pending/grace_expired — an active row is a
    live entitlement and must always be reconciled, however old."""
    sub = await _plus_sub(
        db_session, sample_family,
        status="active", paypal_id="I-OLD-ACTIVE",
        period_end=datetime.now(timezone.utc) + timedelta(days=10),
    )
    sub.updated_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.get_subscription",
        return_value={
            "subscription_id": "I-OLD-ACTIVE",
            "status": "ACTIVE",
            "plan_id": "P-X",
            "next_billing_at": None,
        },
    ) as mock_get:
        await reconcile_with_paypal(db_session)

    mock_get.assert_called_once()


# ---------------------------------------------------------------------------
# Grace-expiry pass: final "subscription ended" email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grace_expiry_sends_final_email_exactly_once(
    db_session, sample_family
):
    """The downgrade to grace_expired sends the bilingual 'subscription
    ended' email — and repeated sweep runs can never re-send it (the
    transition is one-shot)."""
    from app.core.config import settings

    sub = await _plus_sub(
        db_session, sample_family,
        status="payment_failed", paypal_id="I-GRACE-MAIL",
    )
    sub.payment_failure_at = datetime.now(timezone.utc) - timedelta(
        days=settings.BILLING_GRACE_DAYS + 1
    )
    await db_session.commit()

    with patch(
        "app.services.email_service.EmailService.send_subscription_ended_email",
        new=AsyncMock(return_value=1),
    ) as mock_email:
        n1 = await downgrade_grace_expired_subscriptions(db_session)
        n2 = await downgrade_grace_expired_subscriptions(db_session)

    assert n1 == 1
    assert n2 == 0  # second run: row already grace_expired, nothing selected
    mock_email.assert_awaited_once()
    assert mock_email.await_args.args[1] == sample_family.id


@pytest.mark.asyncio
async def test_grace_expiry_email_failure_does_not_block_downgrade(
    db_session, sample_family
):
    """Email dispatch is fire-and-forget: an SMTP explosion must not undo or
    block the downgrade."""
    from app.core.config import settings

    sub = await _plus_sub(
        db_session, sample_family,
        status="payment_failed", paypal_id="I-GRACE-MAIL-BOOM",
    )
    sub.payment_failure_at = datetime.now(timezone.utc) - timedelta(
        days=settings.BILLING_GRACE_DAYS + 1
    )
    await db_session.commit()

    with patch(
        "app.services.email_service.EmailService.send_subscription_ended_email",
        new=AsyncMock(side_effect=RuntimeError("smtp down")),
    ):
        n = await downgrade_grace_expired_subscriptions(db_session)

    assert n == 1
    await db_session.refresh(sub)
    assert sub.status == "grace_expired"
