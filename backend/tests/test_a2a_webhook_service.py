"""A2AWebhookService — enqueue, dispatch, signature, retry sweep, HTTP endpoints."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # cfg-side state updates
    cfg = (await db.execute(
        select(FamilyA2AWebhook).where(FamilyA2AWebhook.family_id == family.id)
    )).scalar_one()
    assert cfg.last_success_at is not None
    assert cfg.failure_count == 0
    assert cfg.last_error is None


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

    cfg = (await db.execute(
        select(FamilyA2AWebhook).where(FamilyA2AWebhook.family_id == family.id)
    )).scalar_one()
    assert cfg.failure_count == 1
    assert cfg.last_error is not None


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


@pytest.mark.asyncio
async def test_sweep_picks_up_pending_with_null_next_retry(db, family, transaction):
    """Pending rows must be picked up by the sweep even when next_retry_at is NULL
    (the freshly-enqueued state). Regression test for the sweep delivery hole."""
    db.add(FamilyA2AWebhook(
        family_id=family.id, url="https://x", secret="s", enabled=True,
    ))
    db.add(A2AWebhookDelivery(
        family_id=family.id, transaction_id=transaction.id,
        payload_json={"a": 1}, status="pending", attempts=0,
        next_retry_at=None,
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


# ---------------------------------------------------------------------------
# HTTP endpoint tests (Task 12): GET / PUT /api/budget/a2a-webhook
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def enabled_webhook(db: AsyncSession, test_family):
    """Create an enabled FamilyA2AWebhook for test_family (used with auth_headers)."""
    row = FamilyA2AWebhook(
        family_id=test_family.id,
        url="https://hook.example/existing",
        secret="existing_secret_xyz",
        enabled=True,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest.mark.asyncio
async def test_put_webhook_returns_secret_on_rotate(
    client: AsyncClient, auth_headers: dict
):
    """PUT with rotate_secret=True must return plaintext secret in response."""
    resp = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "https://hook.example/x", "enabled": True, "rotate_secret": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["secret"] is not None


@pytest.mark.asyncio
async def test_put_rejects_http(client: AsyncClient, auth_headers: dict):
    """PUT with an http:// URL must be rejected with 422 (Pydantic validation)."""
    resp = await client.put(
        "/api/budget/a2a-webhook",
        json={"url": "http://hook.example/x", "enabled": True, "rotate_secret": True},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_webhook_hides_secret(
    client: AsyncClient, auth_headers: dict, enabled_webhook
):
    """GET response must NOT include the secret field."""
    resp = await client.get("/api/budget/a2a-webhook", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "secret" not in body


# ---------------------------------------------------------------------------
# Task 13: /api/internal/a2a/retry sweep endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_internal_retry_requires_token(client: AsyncClient):
    resp = await client.post("/api/internal/a2a/retry")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_internal_retry_calls_sweep(client: AsyncClient, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INTERNAL_API_TOKEN", "tkn")
    called = {}

    async def fake_sweep(db, limit=50):
        called["n"] = limit
        return 3

    monkeypatch.setattr(
        "app.services.budget.a2a_webhook_service.A2AWebhookService.sweep_retries",
        fake_sweep,
    )
    resp = await client.post(
        "/api/internal/a2a/retry",
        headers={"X-Internal-Token": "tkn"},
    )
    assert resp.status_code == 200
    assert resp.json()["processed"] == 3
