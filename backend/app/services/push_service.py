"""Web Push (VAPID) fan-out for parent notifications.

pywebpush is synchronous; wrap each send in asyncio.to_thread so the
gig-submission request path never blocks on Apple/Google push gateway
latency. Dead endpoints (HTTP 410 Gone) are pruned automatically.

If VAPID keys are not configured, sends are skipped with a warning so
local/dev environments work without push setup.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.push_subscription import PushSubscription

log = logging.getLogger(__name__)


class PushService:
    @staticmethod
    def _vapid_configured() -> bool:
        return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)

    @staticmethod
    async def subscribe(
        db: AsyncSession,
        user_id: UUID,
        endpoint: str,
        p256dh: str,
        auth: str,
    ) -> PushSubscription:
        """Upsert a (user, endpoint) subscription. Same endpoint posted
        twice just refreshes the keys + last_seen_at."""
        existing = await db.scalar(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == endpoint,
            )
        )
        if existing:
            existing.p256dh = p256dh
            existing.auth = auth
            await db.commit()
            await db.refresh(existing)
            return existing

        sub = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)
        return sub

    @staticmethod
    async def unsubscribe(db: AsyncSession, user_id: UUID, endpoint: str) -> int:
        result = await db.execute(
            delete(PushSubscription).where(
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint == endpoint,
            )
        )
        await db.commit()
        return result.rowcount or 0

    @staticmethod
    async def send_to_user(
        db: AsyncSession, user_id: UUID, payload: dict[str, Any]
    ) -> int:
        """Fan out a JSON payload to every subscription owned by user_id.

        Returns the count of successful sends. Best-effort: failures
        per endpoint are logged and (if 404/410) drop the row.
        """
        if not PushService._vapid_configured():
            log.warning("VAPID not configured; skipping push to user %s", user_id)
            return 0

        rows = (
            await db.scalars(
                select(PushSubscription).where(PushSubscription.user_id == user_id)
            )
        ).all()
        if not rows:
            return 0

        vapid_claims = {"sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}"}
        body = json.dumps(payload)
        sent = 0
        dead_endpoints: list[str] = []

        for sub in rows:
            try:
                await asyncio.to_thread(
                    webpush,
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                    },
                    data=body,
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims=vapid_claims,
                )
                sent += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    dead_endpoints.append(sub.endpoint)
                else:
                    log.warning(
                        "push send to %s failed (status=%s): %s",
                        sub.endpoint[:60],
                        status,
                        exc,
                    )
            except Exception:
                log.exception("unexpected push send failure for %s", sub.endpoint[:60])

        if dead_endpoints:
            await db.execute(
                delete(PushSubscription).where(
                    PushSubscription.user_id == user_id,
                    PushSubscription.endpoint.in_(dead_endpoints),
                )
            )
            await db.commit()
            log.info("pruned %d dead push endpoints for user %s", len(dead_endpoints), user_id)

        return sent

    @staticmethod
    async def fan_out_pending_gig(
        db: AsyncSession,
        family_id: UUID,
        child_name: str,
        gig_title: str,
        points: int,
    ) -> int:
        """Notify every PARENT in the family that a gig is awaiting review."""
        from app.models.user import User, UserRole

        parents = (
            await db.scalars(
                select(User).where(
                    User.family_id == family_id,
                    User.role == UserRole.PARENT,
                    User.is_active.is_(True),
                )
            )
        ).all()
        if not parents:
            return 0

        payload = {
            "title": "Gig awaiting approval",
            "body": f"{child_name} submitted: {gig_title} ({points} pts)",
            "url": "/parent/approvals",
            "tag": "gig-pending",
        }
        total = 0
        for parent in parents:
            total += await PushService.send_to_user(db, parent.id, payload)
        return total
