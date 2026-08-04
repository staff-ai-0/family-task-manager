"""Plan credit grants — the single internal entitlement mechanism.

Every credit the app gives away (coupon redemption, referral reward,
operator comp) is a PlanCreditGrant row. premium.get_family_plan_by_id
resolves a tier floor from the active ones.

Nothing here touches a PayPal-linked column. That is deliberate and load
bearing: the nightly reconcile sweep overwrites
family_subscriptions.current_period_end from PayPal's next_billing_at, so a
credit stored there would be silently erased.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.premium import (
    ENTITLED_STATUSES,
    PLAN_ORDER,
    _payment_failed_within_grace,
)
from app.models.plan_credit import CREDIT_SOURCES, PlanCreditGrant
from app.models.subscription import FamilySubscription, SubscriptionPlan

# Tiers a credit may grant. 'free' is excluded: granting it is a no-op that
# would read as a bug at the call site.
GRANTABLE_TIERS = ("plus", "pro")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a possibly-naive datetime to UTC-aware (asyncpg round-trips)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class PlanCreditService:
    """Create, resolve and revoke plan credit grants."""

    @staticmethod
    async def active_grants(
        db: AsyncSession, family_id: UUID
    ) -> list[PlanCreditGrant]:
        """Grants entitling *family_id* right now.

        Active = not revoked, already started, and either open-ended
        (lifetime) or not yet ended.
        """
        now = datetime.now(timezone.utc)
        rows = (
            await db.execute(
                select(PlanCreditGrant).where(
                    PlanCreditGrant.family_id == family_id,
                    PlanCreditGrant.revoked_at.is_(None),
                    PlanCreditGrant.starts_at <= now,
                    or_(
                        PlanCreditGrant.ends_at.is_(None),
                        PlanCreditGrant.ends_at > now,
                    ),
                )
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def visible_grants(
        db: AsyncSession, family_id: UUID
    ) -> list[PlanCreditGrant]:
        """Grants worth SHOWING: the active ones plus the queued ones.

        Deliberately NOT the entitlement query — `active_grants` owns that,
        and adding queued rows there would hand out a tier before its window
        opens. This exists because the >=-tier rule makes queuing normal: a
        second Plus code, or any comp handed to a payer, starts in the
        future. Reading only `active_grants` renders those as nothing at
        all, so a successful redemption looks like a no-op (the family
        retries and gets 409) and a successful comp looks unapplied (the
        operator clicks again, and comps STACK — every click is another 30
        free days). Callers must render `starts_at` so a queued grant reads
        as pending rather than live.
        """
        now = datetime.now(timezone.utc)
        rows = (
            await db.execute(
                select(PlanCreditGrant)
                .where(
                    PlanCreditGrant.family_id == family_id,
                    PlanCreditGrant.revoked_at.is_(None),
                    or_(
                        PlanCreditGrant.ends_at.is_(None),
                        PlanCreditGrant.ends_at > now,
                    ),
                )
                .order_by(PlanCreditGrant.starts_at)
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def floor_tier(db: AsyncSession, family_id: UUID) -> Optional[str]:
        """Highest tier the family's active credits entitle it to, or None."""
        grants = await PlanCreditService.active_grants(db, family_id)
        if not grants:
            return None
        return max(grants, key=lambda g: PLAN_ORDER.get(g.tier, 0)).tier

    @staticmethod
    async def next_window_start(
        db: AsyncSession, family_id: UUID, *, tier: str
    ) -> datetime:
        """When a newly granted credit of *tier* should begin.

        The unified rule: a grant starts at the first moment the family is
        NOT already entitled at >= *tier* from another source. That "other
        source" is either of two anchors — the family's own queued credits,
        or a live paid subscription — and BOTH are scoped the same way: only
        defer behind something that already covers (tier >= *tier*), never
        behind something *tier* itself outranks.

        Anchor 1 — the family's last queued credit whose tier
        outranks-or-equals *tier* (PLAN_ORDER). A Pro comp must never wait
        behind an already-queued Plus credit — the better tier would sit
        unused for no reason, and floor_tier's job is to always report the
        best tier active RIGHT NOW. But a Plus grant issued while a Pro
        grant is active must not run in parallel underneath the Pro floor —
        that would burn the Plus days for nothing, since Pro already
        dominates them — so it queues to start when the Pro grant ends.

        Anchor 2 — a live paid subscription's current_period_end, but ONLY
        when the paid plan's tier outranks-or-equals *tier*. The spec's own
        example: a family paying for Plus that receives a Pro grant sees it
        take effect immediately — the paid Plus period does not already
        cover Pro, so there is nothing to defer behind, and floor_tier /
        get_family_plan_by_id must be able to see the Pro floor right away.
        A same-or-lower-tier credit (Plus-on-Plus, or Plus-on-Pro) still
        defers to current_period_end, staying genuinely additive rather than
        wasted in parallel with time already paid for. A paid plan name
        outside PLAN_ORDER ranks 0, which never defers (the safe direction —
        the grant starts now rather than silently vanishing behind an
        unranked plan).

        *tier* is required (no tier-agnostic default): every real caller
        resolves to one of grant()/floor_tier()/active_grants()/revoke(),
        all of which know the tier in question, and a caller that forgot to
        pass tier would silently fall back to the tier-agnostic bug this
        scoping exists to fix.

        Lifetime grants (ends_at IS NULL) are skipped: there is nothing to
        queue behind "forever", and treating them as infinite would make
        every later grant unreachable.
        """
        now = datetime.now(timezone.utc)
        base = now

        anchor_tiers = [t for t in GRANTABLE_TIERS if PLAN_ORDER[t] >= PLAN_ORDER[tier]]
        latest_end = (
            await db.execute(
                select(PlanCreditGrant.ends_at)
                .where(
                    PlanCreditGrant.family_id == family_id,
                    PlanCreditGrant.revoked_at.is_(None),
                    PlanCreditGrant.ends_at.is_not(None),
                    PlanCreditGrant.tier.in_(anchor_tiers),
                )
                .order_by(PlanCreditGrant.ends_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        latest_end = _aware(latest_end)
        if latest_end is not None and latest_end > base:
            base = latest_end

        # Read-only: we never mutate the subscription or plan rows. Join
        # to the plan for its name rather than touching sub.plan — that
        # relationship attribute lazy-loads and is unsafe under async.
        sub_row = (
            await db.execute(
                select(FamilySubscription, SubscriptionPlan.name)
                .join(
                    SubscriptionPlan,
                    FamilySubscription.plan_id == SubscriptionPlan.id,
                )
                .where(FamilySubscription.family_id == family_id)
            )
        ).one_or_none()
        if sub_row is not None:
            sub, paid_plan_name = sub_row
            # The grace check has to match premium's, not just ENTITLED_STATUSES:
            # a grace-EXPIRED payment_failed sub still carries that status until
            # the daily sweep flips it, and premium already treats such a family
            # as free. Deferring behind it would push a code the family redeems
            # in that window out to a period end they are not being entitled by
            # — and unlike the status, the starts_at we bake into the grant row
            # is not something the sweep comes back and fixes.
            if (
                sub.paypal_subscription_id
                and sub.status in ENTITLED_STATUSES
                and not (
                    sub.status == "payment_failed"
                    and not _payment_failed_within_grace(sub)
                )
                and PLAN_ORDER.get(paid_plan_name, 0) >= PLAN_ORDER[tier]
            ):
                paid_end = _aware(sub.current_period_end)
                if paid_end is not None and paid_end > base:
                    base = paid_end

        return base

    @staticmethod
    async def grant(
        db: AsyncSession,
        *,
        family_id: UUID,
        source: str,
        tier: str,
        duration_days: Optional[int] = None,
        coupon_id: Optional[UUID] = None,
        granted_by_user_id: Optional[UUID] = None,
        reason: Optional[str] = None,
    ) -> PlanCreditGrant:
        """Create a credit window. Does NOT commit — the caller owns the
        transaction, so a grant and its audit row land together or not at all.

        ``duration_days=None`` creates a lifetime grant.

        Takes a per-family Postgres advisory xact lock BEFORE computing the
        window (next_window_start reads existing grants + the subscription
        row; the insert below adds a new one), and holds it for the rest of
        the transaction. This serializes EVERY grant writer for the same
        family — referral rewards, operator comps, and coupon redemptions —
        across concurrent transactions. Without it, two grants to the same
        family computed in separate transactions could each see no anchor
        and both start "now": a family earning two 30-day credits
        concurrently would get 30 days instead of 60. Structural here
        (rather than left to each call site) so every current and future
        writer is covered for free — a caller cannot forget to take it.

        The lock is transaction-scoped (``pg_advisory_xact_lock``) and
        self-releasing on commit or rollback, so there is no unlock or
        timeout to manage. It is also idempotent WITHIN one transaction —
        re-locking the same key (e.g. a caller that grants twice to the same
        family in one transaction) is a no-op, not a self-deadlock — so
        nothing here needs to track whether it already holds the lock.
        """
        if source not in CREDIT_SOURCES:
            raise ValueError(f"Unknown credit source: {source!r}")
        if tier not in GRANTABLE_TIERS:
            raise ValueError(f"Not a grantable tier: {tier!r}")
        if duration_days is not None and duration_days < 1:
            raise ValueError("duration_days must be >= 1 or None (lifetime)")

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 13))"),
            {"key": f"plan-credit:{family_id}"},
        )

        starts_at = await PlanCreditService.next_window_start(
            db, family_id, tier=tier
        )
        ends_at = (
            starts_at + timedelta(days=duration_days)
            if duration_days is not None
            else None
        )
        row = PlanCreditGrant(
            family_id=family_id,
            source=source,
            coupon_id=coupon_id,
            tier=tier,
            starts_at=starts_at,
            ends_at=ends_at,
            granted_by_user_id=granted_by_user_id,
            reason=reason,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def revoke(
        db: AsyncSession,
        *,
        grant_id: UUID,
        family_id: Optional[UUID] = None,
    ) -> Optional[PlanCreditGrant]:
        """Soft-revoke a grant. Does NOT commit. Returns None if not found.

        Never DELETE: the row is the audit trail for a credit that was once
        live. Pass *family_id* to scope the lookup when the caller is not an
        operator.
        """
        query = select(PlanCreditGrant).where(PlanCreditGrant.id == grant_id)
        if family_id is not None:
            query = query.where(PlanCreditGrant.family_id == family_id)
        row = (await db.execute(query)).scalar_one_or_none()
        if row is None:
            return None
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
        return row
