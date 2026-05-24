"""Stripe billing routes (W9.4)."""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.exceptions import ValidationException
from app.core.type_utils import to_uuid_required
from app.models import User
from app.services.stripe_service import StripeService


router = APIRouter()


class CheckoutRequest(BaseModel):
    plan_name: str = Field(..., pattern="^(plus|pro)$")
    billing_cycle: str = Field(..., pattern="^(monthly|annual)$")
    success_url: str = Field(..., max_length=512)
    cancel_url: str = Field(..., max_length=512)


@router.get("/health")
async def stripe_health(
    current_user: User = Depends(require_parent_role),
):
    return {
        "configured": StripeService.is_configured(),
        "webhook_configured": bool(settings.STRIPE_WEBHOOK_SECRET),
    }


@router.post("/checkout")
async def create_checkout(
    data: CheckoutRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    if not StripeService.is_configured():
        raise HTTPException(status_code=503, detail="Stripe not configured")
    try:
        result = await StripeService.create_checkout_session(
            db,
            family_id=to_uuid_required(current_user.family_id),
            user_email=current_user.email,
            plan_name=data.plan_name,
            billing_cycle=data.billing_cycle,
            success_url=data.success_url,
            cancel_url=data.cancel_url,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return result


class PortalRequest(BaseModel):
    return_url: str = Field(..., max_length=512)


@router.post("/portal")
async def create_portal(
    data: PortalRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Returns Stripe billing portal URL for customer self-service."""
    if not StripeService.is_configured():
        raise HTTPException(status_code=503, detail="Stripe not configured")
    try:
        result = await StripeService.create_portal_session(
            db,
            family_id=to_uuid_required(current_user.family_id),
            return_url=data.return_url,
        )
    except ValidationException as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")
    return result


@router.post("/webhook")
async def webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Stripe webhook receiver. Verifies signature when STRIPE_WEBHOOK_SECRET
    is set; otherwise accepts payload as-is (dev only)."""
    payload = await request.body()
    if settings.STRIPE_WEBHOOK_SECRET and stripe_signature:
        import stripe
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid signature: {exc}")
        event_dict = (
            event if isinstance(event, dict) else event.to_dict()
        )
    else:
        import json
        try:
            event_dict = json.loads(payload.decode())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

    status_msg = await StripeService.handle_webhook_event(db, event_dict)
    return {"status": status_msg or "ignored"}
