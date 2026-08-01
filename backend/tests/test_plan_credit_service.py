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
