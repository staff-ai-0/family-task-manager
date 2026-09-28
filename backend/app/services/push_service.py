"""Web Push (VAPID) fan-out for parent notifications.

pywebpush is synchronous; wrap each send in asyncio.to_thread so the
gig-submission request path never blocks on Apple/Google push gateway
latency. Dead endpoints (404/410, or 403 for a subscription made with another VAPID key) are pruned automatically.

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


def _derive_public_key(private_key: str) -> str:
    """Public key (X9.62 uncompressed point, base64url, unpadded) of a VAPID
    private key, loaded exactly the way pywebpush loads it for a real send
    (``Vapid.from_string``: raw 32-byte or DER, base64url). Raises on a key
    pywebpush could not use either."""
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    vapid = Vapid.from_string(private_key=private_key)
    point = vapid.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(point).rstrip(b"=").decode()


# 403 bodies that mean "this subscription was made with a different VAPID
# key" — the subscription is unusable forever, same as 404/410. Any other 403
# (e.g. Apple BadJwtToken) is OUR bug, not the device's: log it, never prune,
# or one bad deploy would silently wipe every device.
_KEY_MISMATCH_MARKERS = ("VapidPkHashMismatch", "does not correspond")


def _push_failure_reason(exc: WebPushException) -> str:
    """Provider's reason for a failed send: Apple's JSON ``reason`` when the
    body parses, else the first 200 chars of the body (FCM sends text)."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    try:
        text = resp.text or ""
    except Exception:
        return ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return text[:200]
    if isinstance(data, dict) and data.get("reason"):
        return str(data["reason"])
    return text[:200]


def _is_dead_subscription(status: int | None, reason: str) -> bool:
    if status in (404, 410):
        return True
    return status == 403 and any(m in reason for m in _KEY_MISMATCH_MARKERS)


class PushService:
    @staticmethod
    def _vapid_configured() -> bool:
        return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)

    @staticmethod
    def keypair_status() -> dict[str, Any]:
        """Is the configured VAPID pair one a real send can use?

        ``valid_keys`` means the private key loads and derives exactly the
        configured public key. Never raises and never returns key material:
        on failure ``error`` is an exception class name or "KeyMismatch".
        """
        pub = (settings.VAPID_PUBLIC_KEY or "").strip().rstrip("=")
        priv = (settings.VAPID_PRIVATE_KEY or "").strip()
        if not (pub and priv):
            return {"configured": False, "valid_keys": False, "error": None}
        try:
            derived = _derive_public_key(priv)
        except Exception as exc:
            return {"configured": True, "valid_keys": False, "error": type(exc).__name__}
        if derived != pub:
            return {"configured": True, "valid_keys": False, "error": "KeyMismatch"}
        return {"configured": True, "valid_keys": True, "error": None}

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

        # Explicit exp: py-vapid's default is now + EXACTLY 86400s, and RFC
        # 8292 caps exp at "not more than 24 hours" — an Apple node whose
        # clock trails ours by seconds computes >24h and rejects the token
        # with an intermittent 403 BadJwtToken (prod 2026-08-10). 12h keeps
        # us far from the boundary.
        import time
        vapid_claims = {
            "sub": f"mailto:{settings.VAPID_CLAIM_EMAIL}",
            "exp": int(time.time()) + 12 * 3600,
        }
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
                reason = _push_failure_reason(exc)
                if _is_dead_subscription(status, reason):
                    dead_endpoints.append(sub.endpoint)
                    log.info(
                        "pruning push endpoint %s (status=%s reason=%s)",
                        sub.endpoint[:60], status, reason,
                    )
                else:
                    log.warning(
                        "push send to %s failed (status=%s reason=%s): %s",
                        sub.endpoint[:60], status, reason, exc,
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

        # Task-review queue (chores + bonus tasks → points) — "gig" wording is
        # reserved for the cash gig board (see gig_claim_service pushes).
        payload = {
            "title": "Task awaiting approval",
            "body": f"{child_name} submitted: {gig_title} ({points} pts)",
            "url": "/parent/approvals",
            "tag": "gig-pending",
        }
        total = 0
        for parent in parents:
            total += await PushService.send_to_user(db, parent.id, payload)
        return total
