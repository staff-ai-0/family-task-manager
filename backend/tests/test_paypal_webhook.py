"""Tests for /api/subscriptions/webhook endpoint."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.models.subscription import FamilySubscription, SubscriptionPlan


FIXTURES = Path(__file__).parent / "fixtures" / "paypal_webhooks"

# Honor the runtime environment for the Redis dedupe path: inside the dev
# container Redis is at redis://redis:6379/0 and in CI at localhost:6379.
# Hardcoding localhost silently no-ops the dedupe in the container (the route
# swallows connection errors by design), so the dedupe test never actually
# exercised Redis there.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis_available() -> bool:
    """True if the dedupe Redis is reachable AND writable from this test run.

    A write round-trip (not just ping) because the dedupe needs SET to work:
    a Redis stuck in MISCONF read-only mode answers PING but silently no-ops
    _mark_processed, so duplicate detection would never engage.
    """
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1)
        try:
            probe = "paypal:event:_test_probe"
            client.set(probe, "1", ex=60)
            client.delete(probe)
        finally:
            client.close()
        return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _mute_email_transport():
    """Webhook transitions dispatch billing emails; never hit SMTP in tests."""
    with patch(
        "app.services.email_service.EmailService._send",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_webhook_dedupe_keys():
    """Clear paypal:event:* dedupe marks before each test.

    The fixture payloads carry static event ids and _mark_processed writes
    them to Redis with a 7-day TTL — with a live Redis, marks left by a
    previous run (or a previous test in this file) would flag first
    deliveries as duplicates and skip the state transitions under test.
    """
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1)
        try:
            for key in client.scan_iter("paypal:event:*"):
                client.delete(key)
        finally:
            client.close()
    except Exception:
        pass  # Redis unreachable — dedupe is a no-op, nothing to clear
    yield


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _headers():
    return {
        "Paypal-Transmission-Id": "x",
        "Paypal-Transmission-Time": "x",
        "Paypal-Cert-Url": "x",
        "Paypal-Auth-Algo": "SHA256withRSA",
        "Paypal-Transmission-Sig": "x",
    }


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client):
    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=False,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_activated_flips_subscription(
    client, db_session, sample_family
):
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plan)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="pending",
        paypal_subscription_id="I-WEBHOOK-SUB-123",
    )
    db_session.add(sub)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_webhook_dedupes_by_event_id(client, db_session, sample_family):
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plan)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="pending",
        paypal_subscription_id="I-WEBHOOK-SUB-123",
    )
    db_session.add(sub)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        r1 = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )
        r2 = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    if _redis_available():
        # Regression (launch-p0 review): REDIS_URL now comes from the env, so
        # wherever Redis is live (dev container, CI) the dedupe must actually
        # engage — first delivery processed, retry flagged as duplicate.
        assert r1.json().get("duplicate") is not True
        assert r2.json().get("duplicate") is True


@pytest.mark.asyncio
async def test_webhook_cancelled_sets_period_end_flag(
    client, db_session, sample_family
):
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plan)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-WEBHOOK-SUB-123",
    )
    db_session.add(sub)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("cancelled"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.cancel_at_period_end is True
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_webhook_payment_failed(client, db_session, sample_family):
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plan)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-WEBHOOK-SUB-123",
    )
    db_session.add(sub)
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("payment_failed"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "payment_failed"
    assert sub.payment_failure_at is not None


async def _make_sub(db_session, sample_family, *, status, payment_failure_at=None):
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    db_session.add(plan)
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status=status,
        paypal_subscription_id="I-WEBHOOK-SUB-123",
        payment_failure_at=payment_failure_at,
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


@pytest.mark.asyncio
async def test_webhook_sale_completed_recovers_payment_failed(
    client, db_session, sample_family
):
    """PAYMENT.SALE.COMPLETED (id in resource.billing_agreement_id) flips a
    payment_failed sub back to active and clears the dunning marker."""
    from datetime import datetime, timedelta, timezone

    sub = await _make_sub(
        db_session, sample_family,
        status="payment_failed",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("payment_sale_completed"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.payment_failure_at is None
    assert sub.current_period_end is not None


@pytest.mark.asyncio
async def test_webhook_suspended_starts_dunning(client, db_session, sample_family):
    """BILLING.SUBSCRIPTION.SUSPENDED gets payment_failed-like handling."""
    sub = await _make_sub(db_session, sample_family, status="active")

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("suspended"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "payment_failed"
    assert sub.payment_failure_at is not None


async def _make_staged_change_sub(db_session, sample_family):
    """A live sub with a staged plan-change checkout whose pending PayPal id
    matches the activated.json fixture (I-WEBHOOK-SUB-123)."""
    plus = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=500,
        price_annual_cents=5000,
        limits={"max_family_members": 6},
    )
    pro = SubscriptionPlan(
        name="pro",
        display_name="Pro",
        display_name_es="Pro",
        price_monthly_cents=900,
        price_annual_cents=9000,
        limits={"max_family_members": 10},
    )
    db_session.add_all([plus, pro])
    await db_session.commit()
    sub = FamilySubscription(
        family_id=sample_family.id,
        plan_id=plus.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-OLD-SUPERSEDED",
        pending_plan_id=pro.id,
        pending_billing_cycle="monthly",
        pending_paypal_subscription_id="I-WEBHOOK-SUB-123",
    )
    db_session.add(sub)
    await db_session.commit()
    return sub


@pytest.mark.asyncio
async def test_webhook_activated_staged_cancel_failure_flags_review(
    client, db_session, sample_family
):
    """Regression (re-review, MAJOR): the ACTIVATED staged-promotion fallback
    exists precisely for buyers who never return to /activate. When cancelling
    the superseded PayPal sub fails there, the promotion must stand, the
    webhook must still 200, and the row must carry a persistent needs_review
    trace (double-billing risk) — mirroring the /activate route's handling."""
    sub = await _make_staged_change_sub(db_session, sample_family)

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch(
        "app.services.paypal_service.PayPalService.cancel_subscription",
        side_effect=RuntimeError("paypal down"),
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )

    assert resp.status_code == 200
    await db_session.refresh(sub)
    # Promotion stood despite the cancel failure…
    assert sub.status == "active"
    assert sub.paypal_subscription_id == "I-WEBHOOK-SUB-123"
    assert sub.pending_paypal_subscription_id is None
    # …and the double-billing risk left a persistent operator trace.
    assert sub.needs_review is True
    assert "I-OLD-SUPERSEDED" in (sub.review_reason or "")


@pytest.mark.asyncio
async def test_webhook_activated_staged_review_flag_failure_still_200(
    client, db_session, sample_family
):
    """Even if flagging for review ALSO fails, the webhook returns 200 — the
    promotion already committed, so a PayPal retry could never redo the
    cancel; a 5xx would just churn."""
    sub = await _make_staged_change_sub(db_session, sample_family)

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch(
        "app.services.paypal_service.PayPalService.cancel_subscription",
        side_effect=RuntimeError("paypal down"),
    ), patch(
        "app.api.routes.subscriptions_webhook.mark_for_review",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("activated"),
            headers=_headers(),
        )

    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.paypal_subscription_id == "I-WEBHOOK-SUB-123"


@pytest.mark.asyncio
async def test_webhook_refund_marks_for_review_without_downgrade(
    client, db_session, sample_family
):
    """PAYMENT.SALE.REFUNDED is conservative: flag for operator review, no
    automatic downgrade."""
    sub = await _make_sub(db_session, sample_family, status="active")

    with patch(
        "app.services.paypal_service.PayPalService.verify_webhook_signature",
        return_value=True,
    ), patch("app.api.routes.subscriptions_webhook.settings") as mock_settings:
        mock_settings.PAYPAL_WEBHOOK_ID = "WH-CONFIGURED"
        mock_settings.REDIS_URL = REDIS_URL
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("sale_refunded"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "active"  # still entitled
    assert sub.needs_review is True
    assert "PAYMENT.SALE.REFUNDED" in (sub.review_reason or "")
