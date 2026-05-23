"""Tests for Web Push subscription endpoints + fan-out helper."""
from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push_subscription import PushSubscription
from app.models.task_assignment import (
    TaskAssignment,
    AssignmentStatus,
    ApprovalStatus,
)
from app.services.push_service import PushService
from app.services.task_assignment_service import TaskAssignmentService


SUBSCRIBE_BODY = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/AAAA",
    "keys": {"p256dh": "BAAA-fake-p256dh", "auth": "AAAA-fake-auth"},
}


@pytest.mark.asyncio
async def test_subscribe_requires_auth(client: AsyncClient):
    r = await client.post("/api/push/subscribe", json=SUBSCRIBE_BODY)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_subscribe_stores_row(
    client: AsyncClient, auth_headers, db_session: AsyncSession, test_parent_user,
):
    r = await client.post("/api/push/subscribe", json=SUBSCRIBE_BODY, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["endpoint"] == SUBSCRIBE_BODY["endpoint"]

    rows = (
        await db_session.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == test_parent_user.id
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].endpoint == SUBSCRIBE_BODY["endpoint"]
    assert rows[0].p256dh == SUBSCRIBE_BODY["keys"]["p256dh"]


@pytest.mark.asyncio
async def test_subscribe_is_idempotent(client: AsyncClient, auth_headers, db_session, test_parent_user):
    """Same (user, endpoint) just updates keys; no duplicate row."""
    await client.post("/api/push/subscribe", json=SUBSCRIBE_BODY, headers=auth_headers)
    updated = {
        "endpoint": SUBSCRIBE_BODY["endpoint"],
        "keys": {"p256dh": "rotated-p256", "auth": "rotated-auth"},
    }
    r = await client.post("/api/push/subscribe", json=updated, headers=auth_headers)
    assert r.status_code == 200

    rows = (
        await db_session.scalars(
            select(PushSubscription).where(
                PushSubscription.user_id == test_parent_user.id
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].p256dh == "rotated-p256"


@pytest.mark.asyncio
async def test_unsubscribe_removes_row(client: AsyncClient, auth_headers, db_session, test_parent_user):
    await client.post("/api/push/subscribe", json=SUBSCRIBE_BODY, headers=auth_headers)
    r = await client.post(
        "/api/push/unsubscribe",
        json={"endpoint": SUBSCRIBE_BODY["endpoint"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["removed"] == 1
    count = await db_session.scalar(
        select(PushSubscription).where(PushSubscription.user_id == test_parent_user.id)
    )
    assert count is None


@pytest.mark.asyncio
async def test_public_key_503_when_unconfigured(client: AsyncClient, auth_headers):
    """When VAPID_PUBLIC_KEY is empty the endpoint returns 503."""
    from app.core.config import settings
    settings.VAPID_PUBLIC_KEY = ""
    r = await client.get("/api/push/public-key", headers=auth_headers)
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_public_key_returns_when_configured(client: AsyncClient, auth_headers):
    from app.core.config import settings
    settings.VAPID_PUBLIC_KEY = "BTest-VAPID-public-key"
    try:
        r = await client.get("/api/push/public-key", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["public_key"] == "BTest-VAPID-public-key"
    finally:
        settings.VAPID_PUBLIC_KEY = ""


@pytest.mark.asyncio
async def test_send_to_user_noop_without_vapid(db_session, test_parent_user):
    from app.core.config import settings
    settings.VAPID_PRIVATE_KEY = ""
    settings.VAPID_PUBLIC_KEY = ""
    sent = await PushService.send_to_user(
        db_session, test_parent_user.id, {"title": "x", "body": "y"}
    )
    assert sent == 0


@pytest.mark.asyncio
async def test_fan_out_calls_webpush_per_parent(
    db_session, test_family, test_parent_user, test_child_user, gig_template_factory,
):
    """Submitting a gig should trigger PushService.fan_out_pending_gig."""
    # Configure VAPID so send_to_user goes through the real path,
    # but stub webpush to count calls.
    from app.core.config import settings
    settings.VAPID_PRIVATE_KEY = "fake-private-pem"
    settings.VAPID_PUBLIC_KEY = "fake-public"

    # Subscribe the parent
    sub = PushSubscription(
        user_id=test_parent_user.id,
        endpoint="https://fcm.googleapis.com/fcm/send/PARENT-AAA",
        p256dh="p", auth="a",
    )
    db_session.add(sub)
    await db_session.commit()

    today = date.today()
    gig = await gig_template_factory(family=test_family, points=20)
    a = TaskAssignment(
        id=uuid4(), template_id=gig.id, assigned_to=test_child_user.id,
        family_id=test_family.id, assigned_date=today,
        week_of=today - timedelta(days=today.weekday()),
        status=AssignmentStatus.PENDING,
    )
    db_session.add(a)
    await db_session.commit()

    with patch("app.services.push_service.webpush") as mock_webpush:
        await TaskAssignmentService.complete_assignment(
            db_session, a.id, test_family.id, test_child_user.id,
            proof_text="ship it",
        )
        # webpush called at least once (via asyncio.to_thread)
        assert mock_webpush.call_count >= 1
        call_kwargs = mock_webpush.call_args.kwargs
        assert call_kwargs["subscription_info"]["endpoint"].endswith("PARENT-AAA")
        assert "Gig awaiting approval" in call_kwargs["data"]

    settings.VAPID_PRIVATE_KEY = ""
    settings.VAPID_PUBLIC_KEY = ""
