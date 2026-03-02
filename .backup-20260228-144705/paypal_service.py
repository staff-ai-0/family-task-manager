"""
PayPal Payment Service

Handles PayPal payment processing and webhook events.
"""
import paypalrestsdk
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID, uuid4
from datetime import datetime

from app.core.config import settings
from app.core.exceptions import (
    ValidationException,
    NotFoundException,
)
from app.models import User


class PayPalService:
    """Service for PayPal payment operations"""

    def __init__(self):
        """Initialize PayPal SDK"""
        paypalrestsdk.configure({
            "mode": settings.PAYPAL_MODE,  # "sandbox" or "live"
            "client_id": settings.PAYPAL_CLIENT_ID,
            "client_secret": settings.PAYPAL_CLIENT_SECRET
        })

    @staticmethod
    def create_payment(
        amount: float,
        currency: str = "USD",
        description: str = "Family Task Manager Subscription",
        return_url: str = None,
        cancel_url: str = None,
    ) -> Dict[str, Any]:
        """
        Create a PayPal payment
        
        Args:
            amount: Payment amount
            currency: Currency code (USD, EUR, etc.)
            description: Payment description
            return_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment is cancelled
            
        Returns:
            Dict with payment info including approval_url
            
        Raises:
            ValidationException: If payment creation fails
        """
        # Set default URLs if not provided
        if not return_url:
            return_url = f"{settings.BASE_URL}/payment/success"
        if not cancel_url:
            cancel_url = f"{settings.BASE_URL}/payment/cancel"
        
        payment = paypalrestsdk.Payment({
            "intent": "sale",
            "payer": {
                "payment_method": "paypal"
            },
            "redirect_urls": {
                "return_url": return_url,
                "cancel_url": cancel_url
            },
            "transactions": [{
                "item_list": {
                    "items": [{
                        "name": description,
                        "sku": "subscription",
                        "price": str(amount),
                        "currency": currency,
                        "quantity": 1
                    }]
                },
                "amount": {
                    "total": str(amount),
                    "currency": currency
                },
                "description": description
            }]
        })

        if payment.create():
            # Get approval URL
            approval_url = None
            for link in payment.links:
                if link.rel == "approval_url":
                    approval_url = link.href
                    break
            
            return {
                "payment_id": payment.id,
                "approval_url": approval_url,
                "status": payment.state,
            }
        else:
            raise ValidationException(f"PayPal payment creation failed: {payment.error}")

    @staticmethod
    def execute_payment(payment_id: str, payer_id: str) -> Dict[str, Any]:
        """
        Execute/confirm a PayPal payment
        
        Args:
            payment_id: PayPal payment ID
            payer_id: Payer ID from PayPal redirect
            
        Returns:
            Dict with payment execution result
            
        Raises:
            ValidationException: If payment execution fails
        """
        payment = paypalrestsdk.Payment.find(payment_id)

        if payment.execute({"payer_id": payer_id}):
            return {
                "payment_id": payment.id,
                "status": payment.state,
                "payer_email": payment.payer.payer_info.email,
                "amount": payment.transactions[0].amount.total,
                "currency": payment.transactions[0].amount.currency,
            }
        else:
            raise ValidationException(f"PayPal payment execution failed: {payment.error}")

    @staticmethod
    def get_payment_details(payment_id: str) -> Dict[str, Any]:
        """
        Get details of a PayPal payment
        
        Args:
            payment_id: PayPal payment ID
            
        Returns:
            Dict with payment details
            
        Raises:
            NotFoundException: If payment not found
        """
        try:
            payment = paypalrestsdk.Payment.find(payment_id)
            
            return {
                "payment_id": payment.id,
                "status": payment.state,
                "create_time": payment.create_time,
                "update_time": payment.update_time,
                "amount": payment.transactions[0].amount.total if payment.transactions else None,
                "currency": payment.transactions[0].amount.currency if payment.transactions else None,
                "payer_email": payment.payer.payer_info.email if payment.payer and payment.payer.payer_info else None,
            }
        except paypalrestsdk.ResourceNotFound:
            raise NotFoundException(f"Payment {payment_id} not found")

    @staticmethod
    def create_subscription(
        plan_id: str,
        return_url: str = None,
        cancel_url: str = None,
    ) -> Dict[str, Any]:
        """
        Create a PayPal subscription
        
        Args:
            plan_id: PayPal billing plan ID
            return_url: URL to redirect after successful subscription
            cancel_url: URL to redirect if subscription is cancelled
            
        Returns:
            Dict with subscription info including approval_url
            
        Raises:
            ValidationException: If subscription creation fails
        """
        # Set default URLs if not provided
        if not return_url:
            return_url = f"{settings.BASE_URL}/subscription/success"
        if not cancel_url:
            cancel_url = f"{settings.BASE_URL}/subscription/cancel"
        
        # Note: PayPal subscriptions require PayPal REST SDK v2
        # For now, returning a placeholder
        # You'll need to implement this using the v2 API
        raise NotImplementedError("PayPal subscriptions require REST API v2")

    @staticmethod
    def verify_webhook_signature(
        transmission_id: str,
        transmission_time: str,
        cert_url: str,
        auth_algo: str,
        transmission_sig: str,
        webhook_id: str,
        event_body: Dict[str, Any],
    ) -> bool:
        """
        Verify PayPal webhook signature
        
        Args:
            transmission_id: Transmission ID from webhook headers
            transmission_time: Transmission time from webhook headers
            cert_url: Cert URL from webhook headers
            auth_algo: Auth algorithm from webhook headers
            transmission_sig: Transmission signature from webhook headers
            webhook_id: Your webhook ID from PayPal dashboard
            event_body: Webhook event body
            
        Returns:
            True if signature is valid, False otherwise
        """
        return paypalrestsdk.WebhookEvent.verify(
            transmission_id=transmission_id,
            transmission_time=transmission_time,
            cert_url=cert_url,
            auth_algo=auth_algo,
            transmission_sig=transmission_sig,
            webhook_id=webhook_id,
            event_body=event_body,
        )
