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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.premium import ENTITLED_STATUSES, PLAN_ORDER
from app.models.plan_credit import CREDIT_SOURCES, PlanCreditGrant
from app.models.subscription import FamilySubscription

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
    async def floor_tier(db: AsyncSession, family_id: UUID) -> Optional[str]:
        """Highest tier the family's active credits entitle it to, or None."""
        grants = await PlanCreditService.active_grants(db, family_id)
        if not grants:
            return None
        return max(grants, key=lambda g: PLAN_ORDER.get(g.tier, 0)).tier

    @staticmethod
    async def next_window_start(
        db: AsyncSession, family_id: UUID, *, tier: Optional[str] = None
    ) -> datetime:
        """When a newly granted credit should begin.

        The latest of: now, the end of the family's last queued credit AT
        THE SAME TIER, and a live paid subscription's current_period_end.
        Credits are ADDITIVE — a family holding two 30-day codes at the same
        tier gets 60 days, and a payer's free month starts after the time
        they already bought rather than being spent in parallel with it.

        The "latest queued credit" lookup is scoped to *tier* (when given)
        rather than every grant regardless of tier. Otherwise a higher-tier
        comp granted on top of an already-queued lower-tier credit would
        itself get queued behind it — wasting the higher tier for the
        duration of the lower one and breaking floor_tier's job of always
        reporting the best CURRENTLY active tier. Same-tier grants still
        stack head-to-tail so the same benefit is never doubled up in
        parallel. ``tier=None`` (the default, for callers previewing a
        window without a target tier in mind) considers all tiers.

        Lifetime grants (ends_at IS NULL) are skipped: there is nothing to
        queue behind "forever", and treating them as infinite would make
        every later grant unreachable.
        """
        now = datetime.now(timezone.utc)
        base = now

        latest_end_query = select(PlanCreditGrant.ends_at).where(
            PlanCreditGrant.family_id == family_id,
            PlanCreditGrant.revoked_at.is_(None),
            PlanCreditGrant.ends_at.is_not(None),
        )
        if tier is not None:
            latest_end_query = latest_end_query.where(PlanCreditGrant.tier == tier)
        latest_end = (
            await db.execute(
                latest_end_query.order_by(PlanCreditGrant.ends_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        latest_end = _aware(latest_end)
        if latest_end is not None and latest_end > base:
            base = latest_end

        # Read-only: we never mutate the subscription row.
        sub = (
            await db.execute(
                select(FamilySubscription).where(
                    FamilySubscription.family_id == family_id
                )
            )
        ).scalar_one_or_none()
        if (
            sub is not None
            and sub.paypal_subscription_id
            and sub.status in ENTITLED_STATUSES
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
        """
        if source not in CREDIT_SOURCES:
            raise ValueError(f"Unknown credit source: {source!r}")
        if tier not in GRANTABLE_TIERS:
            raise ValueError(f"Not a grantable tier: {tier!r}")
        if duration_days is not None and duration_days < 1:
            raise ValueError("duration_days must be >= 1 or None (lifetime)")

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
