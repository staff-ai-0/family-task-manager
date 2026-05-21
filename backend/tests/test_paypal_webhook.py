"""Tests for /api/subscriptions/webhook endpoint."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.subscription import FamilySubscription, SubscriptionPlan


FIXTURES = Path(__file__).parent / "fixtures" / "paypal_webhooks"


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
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
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
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
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
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
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
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        resp = await client.post(
            "/api/subscriptions/webhook",
            json=_load("payment_failed"),
            headers=_headers(),
        )
    assert resp.status_code == 200
    await db_session.refresh(sub)
    assert sub.status == "payment_failed"
    assert sub.payment_failure_at is not None
