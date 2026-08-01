"""Unified plan-credit mechanism.

Before this, credit was families.referral_bonus_until — one nullable
timestamp, Plus-only, not revocable, with no per-grant audit trail. It could
not express "90 days of Pro", "lifetime comp", or "who redeemed which code".
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.plan_credit import (
    COUPON_KINDS,
    CREDIT_SOURCES,
    Coupon,
    PlanCreditGrant,
)
from app.services.plan_credit_service import PlanCreditService


def test_source_and_kind_vocabularies_are_closed():
    assert CREDIT_SOURCES == ("coupon", "referral", "operator")
    assert COUPON_KINDS == ("launch", "beta", "comp")


@pytest.mark.asyncio
async def test_a_grant_row_persists(db_session, test_family):
    now = datetime.now(timezone.utc)
    db_session.add(
        PlanCreditGrant(
            family_id=test_family.id,
            source="operator",
            tier="pro",
            starts_at=now,
            ends_at=now + timedelta(days=30),
            reason="friends and family",
        )
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            select(PlanCreditGrant).where(
                PlanCreditGrant.family_id == test_family.id
            )
        )
    ).scalar_one()
    assert row.tier == "pro"
    assert row.revoked_at is None
    assert row.coupon_id is None


@pytest.mark.asyncio
async def test_lifetime_grant_has_no_end(db_session, test_family):
    db_session.add(
        PlanCreditGrant(
            family_id=test_family.id,
            source="operator",
            tier="pro",
            starts_at=datetime.now(timezone.utc),
            ends_at=None,
            reason="lifetime comp",
        )
    )
    await db_session.commit()

    row = (
        await db_session.execute(select(PlanCreditGrant))
    ).scalar_one()
    assert row.ends_at is None


@pytest.mark.asyncio
async def test_a_family_cannot_hold_two_grants_from_one_coupon(
    db_session, test_family
):
    """The DB-level anti-double-redeem guard. Mirrors
    uq_referrals_referred_family — the service pre-check is convenience, THIS
    is what survives a concurrent double POST."""
    coupon = Coupon(
        code="LANZAMIENTO",
        kind="launch",
        tier="plus",
        duration_days=30,
    )
    db_session.add(coupon)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    for _ in range(2):
        db_session.add(
            PlanCreditGrant(
                family_id=test_family.id,
                source="coupon",
                coupon_id=coupon.id,
                tier="plus",
                starts_at=now,
                ends_at=now + timedelta(days=30),
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_many_non_coupon_grants_are_allowed(db_session, test_family):
    """UNIQUE(family_id, coupon_id) must not constrain referral/operator
    grants — Postgres treats NULLs as distinct, and a prolific referrer
    legitimately accumulates many."""
    now = datetime.now(timezone.utc)
    for i in range(3):
        db_session.add(
            PlanCreditGrant(
                family_id=test_family.id,
                source="referral",
                tier="plus",
                starts_at=now + timedelta(days=30 * i),
                ends_at=now + timedelta(days=30 * (i + 1)),
            )
        )
    await db_session.commit()

    rows = (await db_session.execute(select(PlanCreditGrant))).scalars().all()
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_coupon_code_is_unique(db_session):
    db_session.add(Coupon(code="BETA2026", kind="beta", tier="pro", duration_days=180))
    await db_session.commit()

    db_session.add(Coupon(code="BETA2026", kind="beta", tier="pro", duration_days=180))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_grant_creates_a_window_starting_now(db_session, test_family):
    before = datetime.now(timezone.utc)
    row = await PlanCreditService.grant(
        db_session,
        family_id=test_family.id,
        source="operator",
        tier="plus",
        duration_days=30,
        reason="test",
    )
    await db_session.commit()

    assert row.starts_at >= before
    assert row.ends_at - row.starts_at == timedelta(days=30)
    assert row.tier == "plus"


@pytest.mark.asyncio
async def test_grant_with_no_duration_is_lifetime(db_session, test_family):
    row = await PlanCreditService.grant(
        db_session,
        family_id=test_family.id,
        source="operator",
        tier="pro",
        duration_days=None,
        reason="lifetime",
    )
    await db_session.commit()
    assert row.ends_at is None


@pytest.mark.asyncio
async def test_grants_stack_additively(db_session, test_family):
    """A second credit must begin where the first ends, not run in parallel
    — otherwise a family holding two 30-day codes gets 30 days, not 60."""
    first = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    second = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert second.starts_at == first.ends_at
    assert second.ends_at - first.starts_at == timedelta(days=60)


@pytest.mark.asyncio
async def test_a_lifetime_grant_does_not_shift_the_next_window(
    db_session, test_family
):
    await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=None,
    )
    await db_session.commit()

    before = datetime.now(timezone.utc)
    later = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert later.starts_at >= before  # not queued behind "forever"


@pytest.mark.asyncio
async def test_credit_begins_after_a_paid_period(db_session, test_family):
    """A payer's free month must start when their paid period ends, or the
    gift is silently spent on time they already bought. This is the rule the
    old ReferralService._grant_referral_month used; keep it."""
    from app.models.subscription import FamilySubscription, SubscriptionPlan

    plan = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        currency="USD", price_monthly_cents=500, price_annual_cents=5_000,
        limits={}, is_active=True, sort_order=10,
    )
    db_session.add(plan)
    await db_session.flush()

    paid_end = datetime.now(timezone.utc) + timedelta(days=20)
    db_session.add(
        FamilySubscription(
            family_id=test_family.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            status="active",
            paypal_subscription_id="I-PAYING",
            current_period_end=paid_end,
        )
    )
    await db_session.commit()

    row = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert row.starts_at == paid_end


@pytest.mark.asyncio
async def test_floor_tier_picks_the_highest_active_grant(db_session, test_family):
    await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    assert await PlanCreditService.floor_tier(db_session, test_family.id) == "pro"


@pytest.mark.asyncio
async def test_floor_tier_ignores_expired_grants(db_session, test_family):
    past = datetime.now(timezone.utc) - timedelta(days=60)
    db_session.add(
        PlanCreditGrant(
            family_id=test_family.id, source="referral", tier="plus",
            starts_at=past, ends_at=past + timedelta(days=30),
        )
    )
    await db_session.commit()

    assert await PlanCreditService.floor_tier(db_session, test_family.id) is None


@pytest.mark.asyncio
async def test_floor_tier_ignores_revoked_grants(db_session, test_family):
    row = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    await PlanCreditService.revoke(db_session, grant_id=row.id)
    await db_session.commit()

    assert await PlanCreditService.floor_tier(db_session, test_family.id) is None


@pytest.mark.asyncio
async def test_floor_tier_ignores_a_future_dated_grant(db_session, test_family):
    """A grant stacked behind a paid period is not active YET."""
    future = datetime.now(timezone.utc) + timedelta(days=10)
    db_session.add(
        PlanCreditGrant(
            family_id=test_family.id, source="referral", tier="plus",
            starts_at=future, ends_at=future + timedelta(days=30),
        )
    )
    await db_session.commit()

    assert await PlanCreditService.floor_tier(db_session, test_family.id) is None


@pytest.mark.asyncio
async def test_grants_are_family_scoped(db_session, test_family, sample_family):
    await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    assert await PlanCreditService.floor_tier(db_session, sample_family.id) is None


@pytest.mark.asyncio
async def test_grant_rejects_an_unknown_source(db_session, test_family):
    with pytest.raises(ValueError):
        await PlanCreditService.grant(
            db_session, family_id=test_family.id, source="marketing",
            tier="plus", duration_days=30,
        )


@pytest.mark.asyncio
async def test_grant_rejects_an_ungrantable_tier(db_session, test_family):
    """Granting 'free' is meaningless and granting an unknown tier would
    resolve to rank 0 silently."""
    with pytest.raises(ValueError):
        await PlanCreditService.grant(
            db_session, family_id=test_family.id, source="operator",
            tier="free", duration_days=30,
        )


@pytest.mark.asyncio
async def test_a_lower_tier_grant_queues_behind_an_active_higher_tier_grant(
    db_session, test_family
):
    """A Plus grant issued while a Pro grant is active must not run in
    parallel underneath the Pro floor — it queues to start exactly when the
    Pro grant ends. (Under same-tier-only queueing this would start "now"
    instead, wasting the Plus days under a Pro window that already covers
    them.)"""
    pro = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    plus = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert plus.starts_at == pro.ends_at


@pytest.mark.asyncio
async def test_a_higher_tier_grant_never_waits_behind_a_lower_tier_grant(
    db_session, test_family
):
    """A Pro comp issued while a Plus credit is already queued must start
    now, not behind it — the better tier is never made to wait behind the
    worse one."""
    await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    before = datetime.now(timezone.utc)
    pro = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="operator",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    assert pro.starts_at >= before


@pytest.mark.asyncio
async def test_a_revoked_grant_does_not_anchor_the_queue(db_session, test_family):
    """Revoking a grant must free the queue slot it was anchoring —
    otherwise a revoked credit silently pushes the next grant into the
    future forever."""
    first = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    await PlanCreditService.revoke(db_session, grant_id=first.id)
    await db_session.commit()

    before = datetime.now(timezone.utc)
    second = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert second.starts_at >= before


@pytest.mark.asyncio
async def test_a_higher_tier_grant_starts_now_despite_a_lower_tier_paid_sub(
    db_session, test_family
):
    """A Plus payer who receives a Pro grant must see it start immediately.
    The paid Plus period does not already cover Pro, so there is nothing to
    defer behind — the spec's own promise: 'A Pro grant beats a Plus paid
    sub.'"""
    from app.models.subscription import FamilySubscription, SubscriptionPlan

    plan = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        currency="USD", price_monthly_cents=500, price_annual_cents=5_000,
        limits={}, is_active=True, sort_order=10,
    )
    db_session.add(plan)
    await db_session.flush()

    paid_end = datetime.now(timezone.utc) + timedelta(days=20)
    db_session.add(
        FamilySubscription(
            family_id=test_family.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            status="active",
            paypal_subscription_id="I-PAYING",
            current_period_end=paid_end,
        )
    )
    await db_session.commit()

    before = datetime.now(timezone.utc)
    row = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="pro", duration_days=30,
    )
    await db_session.commit()

    assert row.starts_at >= before
    assert row.starts_at != paid_end


@pytest.mark.asyncio
async def test_a_lower_tier_grant_defers_behind_a_higher_tier_paid_sub(
    db_session, test_family
):
    """A Pro payer who receives a Plus-tier credit (e.g. a referral reward)
    must not have it run in parallel underneath their paid Pro period — Pro
    already covers Plus, so the credit queues to start when the paid period
    ends, same as the same-tier case."""
    from app.models.subscription import FamilySubscription, SubscriptionPlan

    plan = SubscriptionPlan(
        name="pro", display_name="Pro", display_name_es="Pro",
        currency="USD", price_monthly_cents=1_500, price_annual_cents=15_000,
        limits={}, is_active=True, sort_order=20,
    )
    db_session.add(plan)
    await db_session.flush()

    paid_end = datetime.now(timezone.utc) + timedelta(days=20)
    db_session.add(
        FamilySubscription(
            family_id=test_family.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            status="active",
            paypal_subscription_id="I-PAYING",
            current_period_end=paid_end,
        )
    )
    await db_session.commit()

    row = await PlanCreditService.grant(
        db_session, family_id=test_family.id, source="referral",
        tier="plus", duration_days=30,
    )
    await db_session.commit()

    assert row.starts_at == paid_end
