"""
PayPal webhook endpoint.

Public (unauthenticated) — PayPal posts here. Signature verified using the
shared webhook_id, events deduplicated via Redis, dispatched to
subscription_state transitions.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status

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


async def _dedupe_event(event_id: str) -> bool:
    """
    Return True if this event_id was NOT seen before (i.e. proceed),
    False if it's a duplicate. On any Redis failure, return True so the
    event proceeds — better to risk an idempotent reapply than to drop.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            result = await client.set(
                f"paypal:event:{event_id}",
                "1",
                ex=EVENT_TTL_SECONDS,
                nx=True,
            )
            return bool(result)
        finally:
            await client.close()
    except Exception as e:
        logger.warning("Redis dedupe failed (proceeding): %s", e)
        return True


@router.post("/webhook", status_code=200)
async def receive_webhook(request: Request):
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
    verified = PayPalService.verify_webhook_signature(
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

    # Dedupe via Redis
    if event_id:
        proceed = await _dedupe_event(event_id)
        if not proceed:
            logger.info("Duplicate webhook event %s, skipping", event_id)
            return {"received": True, "duplicate": True}

    if not subscription_id:
        logger.warning("Webhook event %s has no resource.id", event_id)
        return {"received": True}

    async for db in get_db():
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
            logger.exception("Webhook dispatch failed for %s: %s", event_id, e)
        finally:
            break

    return {"received": True}
