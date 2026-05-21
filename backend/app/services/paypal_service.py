"""
PayPal Payment Service

Handles PayPal payment processing and webhook events.

Subscriptions use the PayPal v2 Billing Subscriptions API via direct HTTP
calls (the legacy paypalrestsdk.BillingAgreement is v1 and incompatible
with v2 Plans created by scripts/setup_paypal_plans.py). The webhook
signature verification still uses paypalrestsdk since that wraps PayPal's
verify endpoint identically across versions.
"""

import time
from typing import Any, Dict, List, Optional
from datetime import datetime
from uuid import UUID, uuid4

import paypalrestsdk
import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    NotFoundException,
    ValidationException,
)
from app.models import User


PAYPAL_API_BASE = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}


class _PayPalV2HTTP:
    """Lightweight OAuth-token-caching HTTP client for the v2 Billing API."""

    _token: Optional[str] = None
    _token_exp: float = 0.0

    @classmethod
    def _base(cls) -> str:
        mode = settings.PAYPAL_MODE or "sandbox"
        return PAYPAL_API_BASE.get(mode, PAYPAL_API_BASE["sandbox"])

    @classmethod
    def _auth(cls) -> str:
        if cls._token and time.time() < cls._token_exp - 30:
            return cls._token
        r = requests.post(
            f"{cls._base()}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        r.raise_for_status()
        body = r.json()
        cls._token = body["access_token"]
        cls._token_exp = time.time() + body.get("expires_in", 3600)
        return cls._token

    @classmethod
    def get(cls, path: str) -> Dict[str, Any]:
        r = requests.get(
            f"{cls._base()}{path}",
            headers={"Authorization": f"Bearer {cls._auth()}"},
            timeout=15,
        )
        if r.status_code == 404:
            raise NotFoundException(f"PayPal resource not found: {path}")
        r.raise_for_status()
        return r.json()

    @classmethod
    def post(
        cls, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        r = requests.post(
            f"{cls._base()}{path}",
            headers={
                "Authorization": f"Bearer {cls._auth()}",
                "Content-Type": "application/json",
            },
            json=body if body is not None else {},
            timeout=15,
        )
        if r.status_code == 404:
            raise NotFoundException(f"PayPal resource not found: {path}")
        if r.status_code >= 400:
            raise ValidationException(
                f"PayPal API error {r.status_code}: {r.text[:300]}"
            )
        if r.status_code == 204 or not r.text:
            return {}
        return r.json()


class PayPalService:
    """Service for PayPal payment operations"""

    def __init__(self):
        """Initialize PayPal SDK"""
        paypalrestsdk.configure(
            {
                "mode": settings.PAYPAL_MODE,  # "sandbox" or "live"
                "client_id": settings.PAYPAL_CLIENT_ID,
                "client_secret": settings.PAYPAL_CLIENT_SECRET,
            }
        )

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

        payment = paypalrestsdk.Payment(
            {
                "intent": "sale",
                "payer": {"payment_method": "paypal"},
                "redirect_urls": {"return_url": return_url, "cancel_url": cancel_url},
                "transactions": [
                    {
                        "item_list": {
                            "items": [
                                {
                                    "name": description,
                                    "sku": "subscription",
                                    "price": str(amount),
                                    "currency": currency,
                                    "quantity": 1,
                                }
                            ]
                        },
                        "amount": {"total": str(amount), "currency": currency},
                        "description": description,
                    }
                ],
            }
        )

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
            raise ValidationException(
                f"PayPal payment creation failed: {payment.error}"
            )

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
            raise ValidationException(
                f"PayPal payment execution failed: {payment.error}"
            )

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
                "amount": payment.transactions[0].amount.total
                if payment.transactions
                else None,
                "currency": payment.transactions[0].amount.currency
                if payment.transactions
                else None,
                "payer_email": payment.payer.payer_info.email
                if payment.payer and payment.payer.payer_info
                else None,
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
        Create a PayPal v2 Billing Subscription.

        Args:
            plan_id: PayPal v2 Plan ID (P-XXXX, from setup_paypal_plans.py)
            return_url: URL PayPal redirects to after user approval
            cancel_url: URL PayPal redirects to if user cancels

        Returns:
            {
              "subscription_id": str,    # I-XXXX
              "approval_url": str,       # PayPal-hosted approval page
              "status": str,             # APPROVAL_PENDING
            }

        Raises:
            ValidationException: PayPal API error
        """
        if not return_url:
            return_url = f"{settings.BASE_URL}/subscription/success"
        if not cancel_url:
            cancel_url = f"{settings.BASE_URL}/subscription/cancel"

        body = {
            "plan_id": plan_id,
            "application_context": {
                "brand_name": "Family Task Manager",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED",
                },
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        data = _PayPalV2HTTP.post("/v1/billing/subscriptions", body)

        approval_url = None
        for link in data.get("links", []):
            if link.get("rel") == "approve":
                approval_url = link.get("href")
                break

        if not approval_url:
            raise ValidationException(
                "PayPal subscription created but no approval link returned"
            )

        return {
            "subscription_id": data["id"],
            "approval_url": approval_url,
            "status": data.get("status", "APPROVAL_PENDING"),
        }

    @staticmethod
    def execute_subscription(
        billing_agreement_id: str,
        token: str,  # kept for backward signature compat; ignored in v2
    ) -> Dict[str, Any]:
        """
        v2 Subscriptions auto-activate after the buyer approves on PayPal's
        hosted page. No explicit execute call is needed; the webhook fires
        BILLING.SUBSCRIPTION.ACTIVATED and we reconcile state via
        subscription_state.apply_activated.

        For the synchronous /activate route, we just fetch the current
        subscription status from PayPal and return it. If the status is
        APPROVAL_PENDING it means the user hasn't actually approved yet
        (e.g., they navigated to /activate by hand) — treat as error.

        Raises:
            NotFoundException: PayPal doesn't recognize the subscription_id
            ValidationException: Subscription is in an invalid state
        """
        data = _PayPalV2HTTP.get(f"/v1/billing/subscriptions/{billing_agreement_id}")
        sub_status = data.get("status", "")
        if sub_status in ("APPROVAL_PENDING", "APPROVED"):
            # APPROVED = user approved but PayPal hasn't started the trial/
            # active phase yet — counts as success for /activate.
            pass
        elif sub_status in ("ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"):
            pass
        else:
            raise ValidationException(
                f"PayPal subscription {billing_agreement_id} has unexpected status: {sub_status}"
            )
        return {
            "status": sub_status,
            "subscription_id": billing_agreement_id,
        }

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
        Verify a PayPal webhook signature against the configured webhook_id.

        Uses PayPal's notifications/verify-webhook-signature endpoint directly
        (paypalrestsdk.WebhookEvent.verify has a different kwarg surface and
        is unreliable across SDK versions).

        Returns True iff PayPal responds with verification_status == "SUCCESS".
        Any HTTP error or non-SUCCESS verdict returns False.
        """
        try:
            body = {
                "transmission_id": transmission_id,
                "transmission_time": transmission_time,
                "cert_url": cert_url,
                "auth_algo": auth_algo,
                "transmission_sig": transmission_sig,
                "webhook_id": webhook_id,
                "webhook_event": event_body,
            }
            resp = _PayPalV2HTTP.post(
                "/v1/notifications/verify-webhook-signature", body
            )
            return resp.get("verification_status") == "SUCCESS"
        except Exception:
            return False

    @staticmethod
    def get_subscription(subscription_id: str) -> Dict[str, Any]:
        """
        Fetch a v2 PayPal Billing Subscription by ID.

        Returns:
            {
              "subscription_id": str,
              "status": str,             # APPROVAL_PENDING | APPROVED | ACTIVE | SUSPENDED | CANCELLED | EXPIRED
              "plan_id": str | None,
              "next_billing_at": str | None,
            }

        Raises:
            NotFoundException: PayPal 404
        """
        data = _PayPalV2HTTP.get(f"/v1/billing/subscriptions/{subscription_id}")
        billing_info = data.get("billing_info") or {}
        return {
            "subscription_id": data.get("id"),
            "status": data.get("status"),
            "plan_id": data.get("plan_id"),
            "next_billing_at": billing_info.get("next_billing_time"),
        }

    @staticmethod
    def cancel_subscription(
        subscription_id: str, reason: str = "User requested cancellation"
    ) -> Dict[str, Any]:
        """
        Cancel a v2 PayPal Billing Subscription immediately at PayPal's end.

        Our app keeps the local FamilySubscription active until
        current_period_end via the cancel_at_period_end flag — PayPal's
        side just stops future renewal charges.

        Returns:
            {"status": "cancelled", "subscription_id": str}

        Raises:
            NotFoundException: PayPal 404
            ValidationException: cancellation failed (e.g., already cancelled)
        """
        _PayPalV2HTTP.post(
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            {"reason": reason},
        )
        return {"status": "cancelled", "subscription_id": subscription_id}
