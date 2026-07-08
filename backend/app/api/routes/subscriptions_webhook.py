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
    apply_expired,
    apply_payment_completed,
    apply_payment_failed,
    mark_for_review,
    promote_pending_checkout,
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
    event_type = payload.get("event_type") or ""
    resource = payload.get("resource", {}) or {}
    # BILLING.SUBSCRIPTION.* events carry the subscription id in resource.id;
    # PAYMENT.SALE.* events carry a sale object whose subscription reference
    # is resource.billing_agreement_id.
    if event_type.startswith("PAYMENT.SALE."):
        subscription_id = resource.get("billing_agreement_id")
    else:
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
            sub = await apply_activated(
                db,
                paypal_subscription_id=subscription_id,
                period_end=period_end,
            )
            if sub is None:
                # Not the live id — maybe a staged plan-change checkout the
                # buyer approved but never returned from (/activate never
                # ran). Promote it here so PayPal-active == locally-active,
                # and cancel the superseded PayPal subscription.
                sub, old_paypal_id = await promote_pending_checkout(
                    db,
                    paypal_subscription_id=subscription_id,
                    period_end=period_end,
                )
                if sub is not None and old_paypal_id:
                    try:
                        await asyncio.to_thread(
                            PayPalService.cancel_subscription,
                            old_paypal_id,
                            reason="Superseded by plan change",
                        )
                    except Exception:
                        logger.warning(
                            "Failed to cancel superseded PayPal sub %s",
                            old_paypal_id, exc_info=True,
                        )
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            await apply_cancelled(db, paypal_subscription_id=subscription_id)
        elif event_type in (
            "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
            # SUSPENDED = PayPal exhausted its own retries / paused billing.
            # Same customer-facing situation as a failed payment: keep the
            # family entitled through the grace window + send dunning email.
            "BILLING.SUBSCRIPTION.SUSPENDED",
        ):
            await apply_payment_failed(
                db, paypal_subscription_id=subscription_id
            )
        elif event_type == "BILLING.SUBSCRIPTION.EXPIRED":
            await apply_expired(db, paypal_subscription_id=subscription_id)
        elif event_type == "PAYMENT.SALE.COMPLETED":
            # Renewal charge or dunning recovery — advance the period /
            # restore entitlements.
            await apply_payment_completed(
                db, paypal_subscription_id=subscription_id
            )
        elif event_type in ("PAYMENT.SALE.REFUNDED", "PAYMENT.SALE.REVERSED"):
            # Conservative by design: refunds/reversals do NOT auto-downgrade
            # (a partial or goodwill refund must not kick a paying family to
            # free). Flag for operator review; if PayPal itself suspends or
            # cancels the subscription over the dispute, those events are
            # handled above.
            await mark_for_review(
                db,
                paypal_subscription_id=subscription_id,
                reason=f"{event_type} (event {event_id})",
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
