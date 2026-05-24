"""Stripe billing service (W9.4).

Lightweight alternative to PayPal. Mirrors the same FamilySubscription
state machine — webhooks map Stripe events to (status, plan_id,
period_end) updates.

Stripe SDK is imported lazily so apps without STRIPE_SECRET_KEY still
boot cleanly. All routes check ``is_configured()`` first and 503 if not.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ValidationException
from app.models.subscription import FamilySubscription, SubscriptionPlan


_PLAN_PRICE_MAP = {
    ("plus", "monthly"): "STRIPE_PRICE_PLUS_MONTHLY",
    ("plus", "annual"):  "STRIPE_PRICE_PLUS_ANNUAL",
    ("pro",  "monthly"): "STRIPE_PRICE_PRO_MONTHLY",
    ("pro",  "annual"):  "STRIPE_PRICE_PRO_ANNUAL",
}


class StripeService:
    @staticmethod
    def is_configured() -> bool:
        return bool(settings.STRIPE_SECRET_KEY)

    @staticmethod
    def _client():
        import stripe  # lazy
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    @staticmethod
    def price_for(plan_name: str, billing_cycle: str) -> str:
        key = _PLAN_PRICE_MAP.get((plan_name, billing_cycle))
        if not key:
            raise ValidationException(
                f"No Stripe price configured for {plan_name}/{billing_cycle}"
            )
        price_id = getattr(settings, key, "")
        if not price_id:
            raise ValidationException(
                f"Setting {key} is empty — set it to a Stripe price ID"
            )
        return price_id

    @staticmethod
    async def create_checkout_session(
        db: AsyncSession,
        family_id: UUID,
        user_email: str,
        plan_name: str,
        billing_cycle: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        """Returns {checkout_url, session_id} for the frontend to redirect."""
        if not StripeService.is_configured():
            raise ValidationException("Stripe not configured")
        stripe = StripeService._client()
        price_id = StripeService.price_for(plan_name, billing_cycle)

        # Reuse existing customer if family already has one.
        fsub_q = select(FamilySubscription).where(
            FamilySubscription.family_id == family_id
        )
        fsub = (await db.execute(fsub_q)).scalar_one_or_none()
        customer_id = fsub.stripe_customer_id if fsub else None

        params = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(family_id),
            "metadata": {
                "family_id": str(family_id),
                "plan_name": plan_name,
                "billing_cycle": billing_cycle,
            },
        }
        if customer_id:
            params["customer"] = customer_id
        else:
            params["customer_email"] = user_email

        session = stripe.checkout.Session.create(**params)
        return {"checkout_url": session.url, "session_id": session.id}

    @staticmethod
    async def handle_webhook_event(
        db: AsyncSession, event: dict
    ) -> Optional[str]:
        """Apply a Stripe webhook event to our local FamilySubscription state.

        Returns a short status string for logging. Unknown event types
        are no-ops (return None).
        """
        etype = event.get("type", "")
        data = (event.get("data") or {}).get("object") or {}

        if etype == "checkout.session.completed":
            family_id_str = (data.get("metadata") or {}).get("family_id")
            plan_name = (data.get("metadata") or {}).get("plan_name")
            billing_cycle = (data.get("metadata") or {}).get("billing_cycle")
            customer_id = data.get("customer")
            sub_id = data.get("subscription")
            if not family_id_str or not plan_name:
                return "missing-metadata"
            family_id = UUID(family_id_str)

            plan_q = select(SubscriptionPlan).where(
                SubscriptionPlan.name == plan_name
            )
            plan = (await db.execute(plan_q)).scalar_one_or_none()
            if plan is None:
                return f"plan-not-found:{plan_name}"

            fsub_q = select(FamilySubscription).where(
                FamilySubscription.family_id == family_id
            )
            fsub = (await db.execute(fsub_q)).scalar_one_or_none()
            if fsub is None:
                fsub = FamilySubscription(
                    family_id=family_id,
                    plan_id=plan.id,
                    billing_cycle=billing_cycle or "monthly",
                    status="active",
                )
                db.add(fsub)
            else:
                fsub.plan_id = plan.id
                fsub.billing_cycle = billing_cycle or fsub.billing_cycle
                fsub.status = "active"
                fsub.cancelled_at = None
                fsub.cancel_at_period_end = False
            fsub.stripe_customer_id = customer_id
            fsub.stripe_subscription_id = sub_id
            await db.commit()
            return "activated"

        if etype == "customer.subscription.deleted":
            sub_id = data.get("id")
            if not sub_id:
                return "missing-sub-id"
            fsub_q = select(FamilySubscription).where(
                FamilySubscription.stripe_subscription_id == sub_id
            )
            fsub = (await db.execute(fsub_q)).scalar_one_or_none()
            if fsub is None:
                return "sub-not-found"
            fsub.status = "cancelled"
            fsub.cancelled_at = datetime.now(timezone.utc)
            await db.commit()
            return "cancelled"

        if etype == "invoice.payment_failed":
            sub_id = data.get("subscription")
            if not sub_id:
                return "missing-sub-id"
            fsub_q = select(FamilySubscription).where(
                FamilySubscription.stripe_subscription_id == sub_id
            )
            fsub = (await db.execute(fsub_q)).scalar_one_or_none()
            if fsub is None:
                return "sub-not-found"
            fsub.payment_failure_at = datetime.now(timezone.utc)
            fsub.status = "past_due"
            await db.commit()
            return "payment-failed"

        return None
