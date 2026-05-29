"""A2AWebhookService — enqueue, dispatch, signature, retry sweep."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.budget.a2a_webhook_service import A2AWebhookService
from app.models.a2a import FamilyA2AWebhook, A2AWebhookDelivery


@pytest.mark.asyncio
async def test_enqueue_skips_when_family_has_no_webhook(db, family, transaction):
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"hello": "world"},
    )
    assert delivery is None


@pytest.mark.asyncio
async def test_enqueue_skips_when_disabled(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=False,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"a": 1},
    )
    assert delivery is None


@pytest.mark.asyncio
async def test_enqueue_creates_delivery_row(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"k": "v"},
    )
    assert delivery is not None
    assert delivery.status == "pending"
    assert delivery.payload_json == {"k": "v"}


@pytest.mark.asyncio
async def test_dispatch_once_signs_and_marks_sent(db, family, transaction):
    secret = "abc123"
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://hook.example/x",
        secret=secret, enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"foo": "bar"},
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 202
    fake_resp.text = "ok"

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.budget.a2a_webhook_service.httpx.AsyncClient",
               return_value=fake_client):
        await A2AWebhookService.dispatch_once(db, delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "sent"
    assert delivery.attempts == 1

    sent_headers = fake_client.post.await_args.kwargs["headers"]
    body = fake_client.post.await_args.kwargs["content"]
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    assert sent_headers["X-A2A-Signature"] == expected


@pytest.mark.asyncio
async def test_dispatch_failure_schedules_retry(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    await db.commit()
    delivery = await A2AWebhookService.enqueue(
        db, family.id, transaction.id, payload={"a": 1},
    )

    fake_client = AsyncMock()
    fake_client.post = AsyncMock(side_effect=RuntimeError("net"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = False

    with patch("app.services.budget.a2a_webhook_service.httpx.AsyncClient",
               return_value=fake_client):
        await A2AWebhookService.dispatch_once(db, delivery.id)

    await db.refresh(delivery)
    assert delivery.status == "failed"
    assert delivery.attempts == 1
    assert delivery.next_retry_at is not None
    assert delivery.next_retry_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_sweep_picks_up_due_failed(db, family, transaction):
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    db.add(A2AWebhookDelivery(
        family_id=family.id, transaction_id=transaction.id,
        payload_json={"a": 1}, status="failed", attempts=1,
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=5),
    ))
    await db.commit()

    ids: list = []

    async def fake_dispatch(_db, _id):
        ids.append(_id)

    with patch.object(A2AWebhookService, "dispatch_once",
                      side_effect=fake_dispatch):
        n = await A2AWebhookService.sweep_retries(db, limit=10)

    assert n == 1
    assert len(ids) == 1
