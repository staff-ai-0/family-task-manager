"""Per-family a2a webhook: enqueue, sign, dispatch, retry."""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AWebhookDelivery, FamilyA2AWebhook


# Exponential backoff schedule for failed deliveries.
_BACKOFF_SCHEDULE = [
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
]
_MAX_ATTEMPTS = len(_BACKOFF_SCHEDULE)
_DISPATCH_TIMEOUT_SECONDS = 10.0


def generate_secret() -> str:
    return secrets.token_hex(32)


class A2AWebhookService:

    @staticmethod
    async def get_config(
        db: AsyncSession, family_id: UUID
    ) -> Optional[FamilyA2AWebhook]:
        result = await db.execute(
            select(FamilyA2AWebhook).where(
                FamilyA2AWebhook.family_id == family_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def upsert_config(
        db: AsyncSession,
        family_id: UUID,
        url: str,
        enabled: bool,
        rotate_secret: bool,
    ) -> tuple[FamilyA2AWebhook, Optional[str]]:
        existing = await A2AWebhookService.get_config(db, family_id)
        plaintext_secret: Optional[str] = None
        if existing is None:
            plaintext_secret = generate_secret()
            row = FamilyA2AWebhook(
                family_id=family_id, url=url,
                secret=plaintext_secret, enabled=enabled,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row, plaintext_secret

        existing.url = url
        existing.enabled = enabled
        if rotate_secret:
            plaintext_secret = generate_secret()
            existing.secret = plaintext_secret
        await db.commit()
        await db.refresh(existing)
        return existing, plaintext_secret

    @staticmethod
    async def enqueue(
        db: AsyncSession,
        family_id: UUID,
        transaction_id: UUID,
        payload: dict,
    ) -> Optional[A2AWebhookDelivery]:
        cfg = await A2AWebhookService.get_config(db, family_id)
        if cfg is None or not cfg.enabled:
            return None
        delivery = A2AWebhookDelivery(
            family_id=family_id,
            transaction_id=transaction_id,
            payload_json=payload,
            status="pending",
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)
        return delivery

    @staticmethod
    async def dispatch_once(db: AsyncSession, delivery_id: UUID) -> None:
        delivery = await db.get(A2AWebhookDelivery, delivery_id)
        if delivery is None:
            return
        cfg = await A2AWebhookService.get_config(db, delivery.family_id)
        if cfg is None or not cfg.enabled:
            delivery.status = "dead"
            delivery.last_error = "no enabled webhook config"
            await db.commit()
            return

        body = json.dumps(delivery.payload_json, separators=(",", ":"),
                          sort_keys=True).encode("utf-8")
        signature = "sha256=" + hmac.new(
            cfg.secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-A2A-Signature": signature,
            "X-A2A-Delivery": str(delivery.id),
            "X-A2A-Schema": "family-budget.receipt.v1",
        }

        delivery.attempts += 1
        try:
            async with httpx.AsyncClient(timeout=_DISPATCH_TIMEOUT_SECONDS) as client:
                resp = await client.post(cfg.url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                delivery.status = "sent"
                delivery.last_error = None
                delivery.next_retry_at = None
                cfg.last_success_at = datetime.now(timezone.utc)
                cfg.failure_count = 0
                cfg.last_error = None
            else:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            delivery.last_error = str(exc)[:500]
            if delivery.attempts >= _MAX_ATTEMPTS:
                delivery.status = "dead"
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delay = _BACKOFF_SCHEDULE[delivery.attempts - 1]
                delivery.next_retry_at = datetime.now(timezone.utc) + delay
            cfg.failure_count += 1
            cfg.last_error = delivery.last_error
        await db.commit()

    @staticmethod
    async def sweep_retries(db: AsyncSession, limit: int = 50) -> int:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(A2AWebhookDelivery.id).where(or_(
                A2AWebhookDelivery.status == "pending",
                and_(
                    A2AWebhookDelivery.status == "failed",
                    A2AWebhookDelivery.next_retry_at.isnot(None),
                    A2AWebhookDelivery.next_retry_at <= now,
                ),
            )).limit(limit)
        )
        ids = [r[0] for r in result.all()]
        for _id in ids:
            await A2AWebhookService.dispatch_once(db, _id)
        return len(ids)
