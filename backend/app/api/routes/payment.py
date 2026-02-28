"""
PayPal Payment routes

Handles PayPal payment creation, execution, and webhooks.
"""

from fastapi import APIRouter, Depends, status, Body, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.services.paypal_service import PayPalService
from app.models import User


router = APIRouter()
logger = logging.getLogger(__name__)


class CreatePaymentRequest(BaseModel):
    """Request model for creating a payment"""
    amount: float = Field(..., description="Payment amount", gt=0)
    currency: str = Field("USD", description="Currency code")
    description: str = Field("Family Task Manager Payment", description="Payment description")
    return_url: Optional[str] = Field(None, description="Success redirect URL")
    cancel_url: Optional[str] = Field(None, description="Cancel redirect URL")


class ExecutePaymentRequest(BaseModel):
    """Request model for executing a payment"""
    payment_id: str = Field(..., description="PayPal payment ID")
    payer_id: str = Field(..., description="PayPal payer ID")


@router.post("/create", status_code=status.HTTP_201_CREATED)
async def create_payment(
    request: CreatePaymentRequest = Body(...),
    current_user: User = Depends(get_current_user),
):
    """
    Create a PayPal payment
    
    Returns an approval_url that the user should be redirected to for payment.
    """
    paypal_service = PayPalService()
    
    payment_info = paypal_service.create_payment(
        amount=request.amount,
        currency=request.currency,
        description=request.description,
        return_url=request.return_url,
        cancel_url=request.cancel_url,
    )
    
    logger.info(f"Payment created for user {current_user.id}: {payment_info['payment_id']}")
    
    return payment_info


@router.post("/execute", status_code=status.HTTP_200_OK)
async def execute_payment(
    request: ExecutePaymentRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute/confirm a PayPal payment after user approval
    
    This endpoint is called after the user is redirected back from PayPal
    with payment_id and payer_id query parameters.
    """
    paypal_service = PayPalService()
    
    result = paypal_service.execute_payment(
        payment_id=request.payment_id,
        payer_id=request.payer_id,
    )
    
    logger.info(f"Payment executed for user {current_user.id}: {result['payment_id']}")
    
    # TODO: Update user subscription status in database
    # TODO: Record payment transaction
    
    return {
        "success": True,
        "message": "Payment successful",
        "payment": result,
    }


@router.get("/details/{payment_id}", status_code=status.HTTP_200_OK)
async def get_payment_details(
    payment_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    Get details of a PayPal payment
    """
    paypal_service = PayPalService()
    
    payment_details = paypal_service.get_payment_details(payment_id)
    
    return payment_details


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paypal_webhook(
    request: Request,
    transmission_id: str = Header(None, alias="PAYPAL-TRANSMISSION-ID"),
    transmission_time: str = Header(None, alias="PAYPAL-TRANSMISSION-TIME"),
    cert_url: str = Header(None, alias="PAYPAL-CERT-URL"),
    auth_algo: str = Header(None, alias="PAYPAL-AUTH-ALGO"),
    transmission_sig: str = Header(None, alias="PAYPAL-TRANSMISSION-SIG"),
):
    """
    Handle PayPal webhook events
    
    PayPal sends webhook events for various payment statuses:
    - PAYMENT.SALE.COMPLETED
    - PAYMENT.SALE.REFUNDED
    - BILLING.SUBSCRIPTION.CREATED
    - etc.
    
    See: https://developer.paypal.com/api/rest/webhooks/event-names/
    """
    from app.core.config import settings
    
    # Get webhook event body
    event_body = await request.json()
    
    # Verify webhook signature
    paypal_service = PayPalService()
    is_valid = paypal_service.verify_webhook_signature(
        transmission_id=transmission_id,
        transmission_time=transmission_time,
        cert_url=cert_url,
        auth_algo=auth_algo,
        transmission_sig=transmission_sig,
        webhook_id=settings.PAYPAL_WEBHOOK_ID,
        event_body=event_body,
    )
    
    if not is_valid:
        logger.warning(f"Invalid PayPal webhook signature")
        return {"status": "invalid_signature"}, 400
    
    # Handle webhook event
    event_type = event_body.get("event_type")
    logger.info(f"Received PayPal webhook: {event_type}")
    
    # TODO: Handle different event types
    # - PAYMENT.SALE.COMPLETED: Update subscription status
    # - PAYMENT.SALE.REFUNDED: Handle refund
    # - BILLING.SUBSCRIPTION.CANCELLED: Deactivate subscription
    # etc.
    
    return {"status": "success", "event_type": event_type}
