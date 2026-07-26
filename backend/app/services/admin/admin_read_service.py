"""Cross-tenant aggregate reads for the operator console.

Every query here deliberately spans families. It exists as a separate module
precisely so BaseFamilyService's family_id filters are never relaxed — that
would silently widen roughly fifty family-scoped services.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AWebhookDelivery
from app.models.budget import BudgetReceiptDraft
from app.models.family import Family
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.user import APPROVAL_PENDING, User

# Subscription statuses that represent a live entitlement backed by PayPal.
# 'past_due' and 'payment_failed' are inside the billing grace window and are
# still paying customers. Anything without a paypal_subscription_id is a comp
# or a free row and must not be counted as revenue.
PAYING_STATUSES = ("active", "past_due", "payment_failed")


class AdminReadService:
    """Read-only aggregates. Never mutates."""

    @staticmethod
    async def platform_pulse(db: AsyncSession) -> dict:
        """One-screen platform state.

        Every actionable-queue or revenue figure excludes rows belonging to
        a closed (soft-deleted) family: receipt_drafts_pending,
        overdue_assignments, mrr, and a2a. The one deliberate exception is
        billing_needs_review — see the comment at that query for why.
        """
        families_total = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_(None))
        )
        families_suspended = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_(None), Family.is_active.is_(False))
        )
        families_pending_purge = await db.scalar(
            select(func.count())
            .select_from(Family)
            .where(Family.deleted_at.is_not(None))
        )
        users_total = await db.scalar(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
        users_verified = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.deleted_at.is_(None), User.email_verified.is_(True))
        )
        users_pending_approval = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.deleted_at.is_(None),
                User.approval_status == APPROVAL_PENDING,
            )
        )
        # Deliberately UNFILTERED by Family.deleted_at. An unresolved
        # refund/chargeback dispute on a family that has since closed its
        # account is exactly the case an operator must still see — soft
        # delete does not settle a dispute, and filtering it out here would
        # hide the disputes most likely to still cost money. Do not add a
        # Family join to this query.
        billing_needs_review = await db.scalar(
            select(func.count())
            .select_from(FamilySubscription)
            .where(FamilySubscription.needs_review.is_(True))
        )
        receipt_drafts_pending = await db.scalar(
            select(func.count())
            .select_from(BudgetReceiptDraft)
            .join(Family, BudgetReceiptDraft.family_id == Family.id)
            .where(
                Family.deleted_at.is_(None),
                BudgetReceiptDraft.status == "pending",
            )
        )
        overdue_assignments = await db.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .join(Family, TaskAssignment.family_id == Family.id)
            .where(
                Family.deleted_at.is_(None),
                TaskAssignment.status == AssignmentStatus.OVERDUE,
            )
        )

        return {
            "families_total": int(families_total or 0),
            "families_suspended": int(families_suspended or 0),
            "families_pending_purge": int(families_pending_purge or 0),
            "users_total": int(users_total or 0),
            "users_verified": int(users_verified or 0),
            "users_pending_approval": int(users_pending_approval or 0),
            "billing_needs_review": int(billing_needs_review or 0),
            "receipt_drafts_pending": int(receipt_drafts_pending or 0),
            "overdue_assignments": int(overdue_assignments or 0),
            "mrr": await AdminReadService.current_state_mrr(db),
            "a2a": await AdminReadService.a2a_health(db),
        }

    @staticmethod
    async def current_state_mrr(db: AsyncSession) -> list[dict]:
        """Monthly recurring revenue implied by TODAY'S subscription rows.

        Not a time series and not reconstructible history: family_subscriptions
        holds one row per family, mutated in place, and plan prices are mutable
        list prices. Reported per currency — there is no stored FX rate, so a
        single summed figure would be fiction. Excludes closed (soft-deleted)
        families: revenue attributed to an account that has already closed is
        simply wrong, even during the grace window before the purge sweep
        flips its subscription status.
        """
        rows = (
            await db.execute(
                select(
                    SubscriptionPlan.currency,
                    SubscriptionPlan.name,
                    FamilySubscription.billing_cycle,
                    SubscriptionPlan.price_monthly_cents,
                    SubscriptionPlan.price_annual_cents,
                    func.count().label("n"),
                )
                .select_from(FamilySubscription)
                .join(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .join(Family, FamilySubscription.family_id == Family.id)
                .where(
                    Family.deleted_at.is_(None),
                    FamilySubscription.status.in_(PAYING_STATUSES),
                    FamilySubscription.paypal_subscription_id.is_not(None),
                    SubscriptionPlan.name != "free",
                )
                .group_by(
                    SubscriptionPlan.currency,
                    SubscriptionPlan.name,
                    FamilySubscription.billing_cycle,
                    SubscriptionPlan.price_monthly_cents,
                    SubscriptionPlan.price_annual_cents,
                )
            )
        ).all()

        per_currency: dict[str, dict] = {}
        for currency, plan_name, cycle, monthly, annual, n in rows:
            bucket = per_currency.setdefault(
                currency, {"currency": currency, "cents": 0, "subscriptions": 0}
            )
            unit = annual // 12 if cycle == "annual" else monthly
            bucket["cents"] += unit * n
            bucket["subscriptions"] += n
        return sorted(per_currency.values(), key=lambda b: b["currency"])

    @staticmethod
    async def a2a_health(db: AsyncSession) -> dict:
        """Outbound bank-matcher webhook delivery health.

        Excludes closed (soft-deleted) families — a stuck delivery for an
        account nobody can act on anymore is noise, not a queue to work.
        """
        now = datetime.now(timezone.utc)
        by_status = dict(
            (
                await db.execute(
                    select(A2AWebhookDelivery.status, func.count())
                    .join(Family, A2AWebhookDelivery.family_id == Family.id)
                    .where(Family.deleted_at.is_(None))
                    .group_by(A2AWebhookDelivery.status)
                )
            ).all()
        )
        overdue_retries = await db.scalar(
            select(func.count())
            .select_from(A2AWebhookDelivery)
            .join(Family, A2AWebhookDelivery.family_id == Family.id)
            .where(
                Family.deleted_at.is_(None),
                A2AWebhookDelivery.status == "pending",
                A2AWebhookDelivery.next_retry_at.is_not(None),
                A2AWebhookDelivery.next_retry_at < now,
            )
        )
        oldest_pending = await db.scalar(
            select(func.min(A2AWebhookDelivery.created_at))
            .join(Family, A2AWebhookDelivery.family_id == Family.id)
            .where(
                Family.deleted_at.is_(None),
                A2AWebhookDelivery.status == "pending",
            )
        )
        return {
            "by_status": {k: int(v) for k, v in by_status.items()},
            "overdue_retries": int(overdue_retries or 0),
            "oldest_pending_at": (
                oldest_pending.isoformat() if oldest_pending else None
            ),
        }
