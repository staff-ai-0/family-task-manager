"""
PayPal webhook endpoint.

Public (unauthenticated) — PayPal posts here. Signature verified using the
shared webhook_id, events deduplicated via Redis, dispatched to
subscription_state transitions.
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services.paypal_service import PayPalService
from app.services.subscription_state import (
    apply_activated,
    apply_cancelled,
    apply_payment_failed,
)


router = APIRouter()
logger = logging.getLogger(__name__)

EVENT_TTL_SECONDS = 7 * 24 * 3600


async def _already_processed(event_id: str) -> bool:
    """True if this event was already fully processed (skip it).

    Read-only — the 'processed' mark is written only AFTER a successful state
    change (see _mark_processed). On Redis failure, return False so the event
    proceeds; the state transitions are idempotent.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            return (await client.get(f"paypal:event:{event_id}")) is not None
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning("Redis dedupe check failed (proceeding): %s", e)
        return False


async def _mark_processed(event_id: str) -> None:
    """Record that this event was successfully handled (so retries are deduped).

    Called ONLY after the state change committed — never before — so a transient
    failure leaves the event un-marked and PayPal's retry can reprocess it.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await client.set(f"paypal:event:{event_id}", "1", ex=EVENT_TTL_SECONDS)
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning("Redis mark-processed failed: %s", e)


@router.post("/webhook", status_code=200)
async def receive_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Verify + dispatch a PayPal webhook event.

    Returns 200 on success/duplicate, 401 on invalid signature. PayPal
    retries non-2xx for up to 24h, so internal parsing failures should
    NOT cause non-2xx responses — log and return 200.
    """
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Webhook body not valid JSON: %s", raw_body[:200])
        return {"received": True}

    event_id = payload.get("id")
    event_type = payload.get("event_type")
    resource = payload.get("resource", {}) or {}
    subscription_id = resource.get("id")

    if not settings.PAYPAL_WEBHOOK_ID:
        logger.error("PAYPAL_WEBHOOK_ID not configured; rejecting webhook")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="webhook not configured",
        )

    headers = request.headers
    verified = await asyncio.to_thread(
        PayPalService.verify_webhook_signature,
        transmission_id=headers.get("paypal-transmission-id", ""),
        transmission_time=headers.get("paypal-transmission-time", ""),
        cert_url=headers.get("paypal-cert-url", ""),
        auth_algo=headers.get("paypal-auth-algo", ""),
        transmission_sig=headers.get("paypal-transmission-sig", ""),
        webhook_id=settings.PAYPAL_WEBHOOK_ID,
        event_body=payload,
    )
    if not verified:
        logger.warning("PayPal webhook signature invalid: %s", event_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )

    # Skip events we already fully processed (the mark is written only after a
    # successful state change below).
    if event_id and await _already_processed(event_id):
        logger.info("Duplicate webhook event %s, skipping", event_id)
        return {"received": True, "duplicate": True}

    if not subscription_id:
        logger.warning("Webhook event %s has no resource.id", event_id)
        return {"received": True}

    try:
        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            next_billing = (resource.get("billing_info") or {}).get(
                "next_billing_time"
            )
            period_end = (
                datetime.fromisoformat(next_billing.replace("Z", "+00:00"))
                if next_billing
                else datetime.now(timezone.utc)
            )
            await apply_activated(
                db,
                paypal_subscription_id=subscription_id,
                period_end=period_end,
            )
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            await apply_cancelled(db, paypal_subscription_id=subscription_id)
        elif event_type == "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
            await apply_payment_failed(
                db, paypal_subscription_id=subscription_id
            )
        else:
            logger.info("Ignoring webhook event_type %s", event_type)
    except Exception as e:
        # Do NOT mark processed and DO return 5xx so PayPal retries — a transient
        # DB failure must not silently drop a subscription state change.
        logger.exception("Webhook dispatch failed for %s: %s", event_id, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="processing failed; will retry",
        )

    # Mark processed only after a successful (or intentionally-ignored) dispatch.
    if event_id:
        await _mark_processed(event_id)

    return {"received": True}
