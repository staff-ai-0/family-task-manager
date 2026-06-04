"""B6: a PayPal webhook whose state change fails must be retriable.

Before: the event was marked processed in Redis BEFORE the state change, and a
dispatch exception was swallowed into a 200. So a transient DB failure both (a)
told PayPal "ok" (no retry) and (b) deduped any retry — the event was lost.
Now: mark processed only AFTER a successful dispatch, and return 5xx on failure.
"""
import uuid

import pytest
from unittest.mock import patch

from app.core.config import settings

WEBHOOK_URL = "/api/subscriptions/webhook"
VERIFY = "app.services.paypal_service.PayPalService.verify_webhook_signature"


def _event(event_type: str, event_id: str, sub_id: str = "sub-x") -> dict:
    return {"id": event_id, "event_type": event_type, "resource": {"id": sub_id}}


async def _redis():
    import redis.asyncio as aioredis

    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


class TestWebhookResilience:
    @pytest.mark.asyncio
    async def test_failed_apply_returns_5xx_and_is_not_marked_processed(
        self, client, monkeypatch
    ):
        monkeypatch.setattr(settings, "PAYPAL_WEBHOOK_ID", "test-wh")
        event_id = "evt-b6fail-" + uuid.uuid4().hex
        rc = await _redis()
        await rc.delete(f"paypal:event:{event_id}")

        with patch(VERIFY, return_value=True), patch(
            "app.api.routes.subscriptions_webhook.apply_activated",
            side_effect=RuntimeError("transient db failure"),
        ):
            r = await client.post(
                WEBHOOK_URL, json=_event("BILLING.SUBSCRIPTION.ACTIVATED", event_id)
            )

        assert r.status_code >= 500, r.text
        marked = await rc.get(f"paypal:event:{event_id}")
        await rc.aclose()
        assert marked is None, "failed event must NOT be marked processed — PayPal must retry"

    @pytest.mark.asyncio
    async def test_successful_event_is_marked_and_then_deduped(self, client, monkeypatch):
        monkeypatch.setattr(settings, "PAYPAL_WEBHOOK_ID", "test-wh")
        event_id = "evt-b6ok-" + uuid.uuid4().hex
        rc = await _redis()
        await rc.delete(f"paypal:event:{event_id}")

        with patch(VERIFY, return_value=True):
            r = await client.post(
                WEBHOOK_URL, json=_event("BILLING.SUBSCRIPTION.SUSPENDED", event_id)
            )
        assert r.status_code == 200, r.text
        assert (await rc.get(f"paypal:event:{event_id}")) == "1"

        with patch(VERIFY, return_value=True):
            r2 = await client.post(
                WEBHOOK_URL, json=_event("BILLING.SUBSCRIPTION.SUSPENDED", event_id)
            )
        await rc.aclose()
        assert r2.json().get("duplicate") is True
