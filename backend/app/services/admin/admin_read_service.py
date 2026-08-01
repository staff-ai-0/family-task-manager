"""Cross-tenant aggregate reads for the operator console.

Every query here deliberately spans families. It exists as a separate module
precisely so BaseFamilyService's family_id filters are never relaxed — that
would silently widen roughly fifty family-scoped services.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.a2a import A2AWebhookDelivery, FamilyA2AWebhook
from app.models.budget import BudgetAccount, BudgetReceiptDraft, BudgetTransaction
from app.models.cash_transaction import CashTransaction
from app.models.family import Family
from app.models.operator_audit import OperatorAuditLog
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.user import APPROVAL_PENDING, User
from app.services.family_deletion_service import FamilyDeletionService
from app.services.plan_credit_service import PlanCreditService

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

    @staticmethod
    async def family_detail(db: AsyncSession, family_id: UUID) -> dict:
        """Everything the support console shows for one family.

        Metadata only — no message bodies, no images, no chat, no DMs. Those
        wait for the moderation phase, which owns the redaction and consent
        design.
        """
        family = await db.scalar(select(Family).where(Family.id == family_id))
        if family is None:
            # 404 here is indistinguishable from the 404 a non-operator gets,
            # which is the point.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Not Found"
            )

        members = (
            await db.execute(
                select(User)
                .where(User.family_id == family_id)
                .order_by(User.created_at.asc())
            )
        ).scalars().all()

        assignment_counts = dict(
            (
                await db.execute(
                    select(TaskAssignment.status, func.count())
                    .where(TaskAssignment.family_id == family_id)
                    .group_by(TaskAssignment.status)
                )
            ).all()
        )

        account_count = await db.scalar(
            select(func.count())
            .select_from(BudgetAccount)
            .where(
                BudgetAccount.family_id == family_id,
                BudgetAccount.deleted_at.is_(None),
            )
        )
        transaction_count = await db.scalar(
            select(func.count())
            .select_from(BudgetTransaction)
            .where(
                BudgetTransaction.family_id == family_id,
                BudgetTransaction.deleted_at.is_(None),
            )
        )
        drafts_pending = await db.scalar(
            select(func.count())
            .select_from(BudgetReceiptDraft)
            .where(
                BudgetReceiptDraft.family_id == family_id,
                BudgetReceiptDraft.status == "pending",
            )
        )

        sub_row = (
            await db.execute(
                select(FamilySubscription, SubscriptionPlan)
                .outerjoin(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .where(FamilySubscription.family_id == family_id)
            )
        ).first()

        webhook = await db.scalar(
            select(FamilyA2AWebhook).where(
                FamilyA2AWebhook.family_id == family_id
            )
        )
        deliveries = dict(
            (
                await db.execute(
                    select(A2AWebhookDelivery.status, func.count())
                    .where(A2AWebhookDelivery.family_id == family_id)
                    .group_by(A2AWebhookDelivery.status)
                )
            ).all()
        )

        recent_cash = (
            await db.execute(
                select(CashTransaction)
                .where(CashTransaction.family_id == family_id)
                .order_by(CashTransaction.created_at.desc())
                .limit(20)
            )
        ).scalars().all()

        return {
            "overview": {
                "id": str(family.id),
                "name": family.name,
                "timezone": family.timezone,
                "is_active": family.is_active,
                "created_at": family.created_at.isoformat(),
                "deleted_at": (
                    family.deleted_at.isoformat() if family.deleted_at else None
                ),
                "purge_after": (
                    (
                        family.deleted_at
                        + timedelta(days=FamilyDeletionService.PURGE_RETENTION_DAYS)
                    ).isoformat()
                    if family.deleted_at
                    else None
                ),
                "join_code": family.join_code,
                "referral_code": family.referral_code,
                "active_credits": [
                    {
                        "tier": g.tier,
                        "source": g.source,
                        "ends_at": g.ends_at.isoformat() if g.ends_at else None,
                    }
                    for g in await PlanCreditService.active_grants(db, family.id)
                ],
                # NULL means ALL modules on, not none. Rendered verbatim so
                # the UI can say so explicitly rather than showing "0 modules".
                "enabled_modules": family.enabled_modules,
                "point_value_cents": family.point_value_cents,
                "gig_term": family.gig_term,
                "ai_processing_consent": family.ai_processing_consent,
                "ai_processing_consent_at": (
                    family.ai_processing_consent_at.isoformat()
                    if family.ai_processing_consent_at
                    else None
                ),
                "onboarding": {
                    "child_invited": family.onboarding_child_invited,
                    "task_created": family.onboarding_task_created,
                    "reward_created": family.onboarding_reward_created,
                    "points_awarded": family.onboarding_points_awarded,
                    "dismissed": family.onboarding_dismissed,
                },
            },
            "members": [
                {
                    "id": str(u.id),
                    "email": u.email,
                    "name": u.name,
                    "role": u.role.value,
                    "is_active": u.is_active,
                    "email_verified": u.email_verified,
                    "approval_status": u.approval_status,
                    "oauth_provider": u.oauth_provider,
                    "points": u.points,
                    "cash_cents": u.cash_cents,
                    "last_seen_at": (
                        u.last_seen_at.isoformat() if u.last_seen_at else None
                    ),
                    "created_at": u.created_at.isoformat(),
                    "deleted_at": (
                        u.deleted_at.isoformat() if u.deleted_at else None
                    ),
                }
                for u in members
            ],
            "economy": {
                "recent_cash_transactions": [
                    {
                        "id": str(tx.id),
                        "user_id": str(tx.user_id),
                        "type": tx.type.value,
                        "amount_cents": tx.amount_cents,
                        "balance_after": tx.balance_after,
                        "jar": tx.jar,
                        "week_of": tx.week_of.isoformat() if tx.week_of else None,
                        "created_at": tx.created_at.isoformat(),
                    }
                    for tx in recent_cash
                ],
            },
            "tasks": {
                "by_status": {
                    s.value if hasattr(s, "value") else str(s): int(n)
                    for s, n in assignment_counts.items()
                },
            },
            "budget": {
                "account_count": int(account_count or 0),
                "transaction_count": int(transaction_count or 0),
                "receipt_drafts_pending": int(drafts_pending or 0),
            },
            "billing": (
                {
                    "plan": sub_row[1].name if sub_row[1] else None,
                    "currency": sub_row[1].currency if sub_row[1] else None,
                    "status": sub_row[0].status,
                    "billing_cycle": sub_row[0].billing_cycle,
                    "paypal_subscription_id": sub_row[0].paypal_subscription_id,
                    "current_period_end": (
                        sub_row[0].current_period_end.isoformat()
                        if sub_row[0].current_period_end
                        else None
                    ),
                    "cancel_at_period_end": sub_row[0].cancel_at_period_end,
                    "payment_failure_at": (
                        sub_row[0].payment_failure_at.isoformat()
                        if sub_row[0].payment_failure_at
                        else None
                    ),
                    "needs_review": sub_row[0].needs_review,
                    "review_reason": sub_row[0].review_reason,
                }
                if sub_row
                else None
            ),
            "integrations": {
                "a2a_webhook": (
                    {
                        "enabled": webhook.enabled,
                        "failure_count": webhook.failure_count,
                        "last_success_at": (
                            webhook.last_success_at.isoformat()
                            if webhook.last_success_at
                            else None
                        ),
                        "last_error": webhook.last_error,
                    }
                    if webhook
                    else None
                ),
                "deliveries_by_status": {
                    k: int(v) for k, v in deliveries.items()
                },
            },
        }

    @staticmethod
    async def billing_review_queue(db: AsyncSession) -> list[dict]:
        """Subscriptions a webhook refused to act on automatically.

        Written by subscription_state.mark_for_review — refunds, reversals,
        and the failed-cancel case that risks double billing. The highest
        signal-to-effort queue in the app.
        """
        rows = (
            await db.execute(
                select(FamilySubscription, SubscriptionPlan, Family)
                .outerjoin(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .join(Family, FamilySubscription.family_id == Family.id)
                .where(FamilySubscription.needs_review.is_(True))
                .order_by(FamilySubscription.updated_at.desc())
            )
        ).all()
        return [
            {
                "family_id": str(fam.id),
                "family_name": fam.name,
                "plan": plan.name if plan else None,
                "status": sub.status,
                "paypal_subscription_id": sub.paypal_subscription_id,
                "review_reason": sub.review_reason,
                "updated_at": sub.updated_at.isoformat(),
            }
            for sub, plan, fam in rows
        ]

    @staticmethod
    async def pending_purge_queue(db: AsyncSession) -> list[dict]:
        """Families inside the recovery window, oldest first."""
        member_counts = (
            select(User.family_id, func.count().label("n"))
            .group_by(User.family_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(Family, member_counts.c.n)
                .outerjoin(member_counts, member_counts.c.family_id == Family.id)
                .where(Family.deleted_at.is_not(None))
                .order_by(Family.deleted_at.asc())
            )
        ).all()
        return [
            {
                "id": str(fam.id),
                "name": fam.name,
                "deleted_at": fam.deleted_at.isoformat(),
                "purge_after": (
                    fam.deleted_at
                    + timedelta(days=FamilyDeletionService.PURGE_RETENTION_DAYS)
                ).isoformat(),
                "member_count": int(n or 0),
            }
            for fam, n in rows
        ]

    @staticmethod
    async def billing_config_health(db: AsyncSession) -> dict:
        """Can the app actually sell a plan right now?

        Wraps app.core.plan_pricing.audit_plan_rows, which has TWO
        consumers: the app.main startup log and this admin endpoint. Both
        run against PRODUCTION data (CI's schema is built with create_all
        and holds no plan rows) — this one on demand, the startup log once
        per boot and only seen if somebody greps for it. Neither BLOCKS
        anything; they observe and report. `scripts/deploy-onprem.sh`'s
        billing smoke check is a separate, independent third check that
        does NOT call audit_plan_rows — it re-derives an equivalent rule
        against the public API instead. It is the only one of the three
        that GATES: a failure there blocks the deploy, while this panel and
        the startup log only ever surface a problem for a human to see.
        """
        from app.core.plan_pricing import audit_plan_rows

        findings = await audit_plan_rows(db)
        return {"healthy": not findings, "findings": findings}

    @staticmethod
    async def audit_log(
        db: AsyncSession,
        *,
        family_id: UUID | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Operator audit trail, newest first."""
        conditions = []
        if family_id is not None:
            conditions.append(OperatorAuditLog.target_family_id == family_id)
        if action:
            conditions.append(OperatorAuditLog.action == action)

        total = await db.scalar(
            select(func.count()).select_from(OperatorAuditLog).where(*conditions)
        )
        rows = (
            await db.execute(
                select(OperatorAuditLog)
                .where(*conditions)
                .order_by(OperatorAuditLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return {
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "items": [
                {
                    "id": str(r.id),
                    "actor_email": r.actor_email,
                    "action": r.action,
                    "target_family_id": (
                        str(r.target_family_id) if r.target_family_id else None
                    ),
                    "target_user_id": (
                        str(r.target_user_id) if r.target_user_id else None
                    ),
                    "params": r.params,
                    "result": r.result,
                    "error": r.error,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
        }
