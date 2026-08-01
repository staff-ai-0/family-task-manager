"""Coupon redemption rules.

Error contract: every reason a code is unusable (unknown, inactive, not yet
valid, expired, exhausted) raises the SAME CouponInvalid, so the endpoint is
not an oracle for which codes exist. Only already-redeemed is distinct — the
family can see that state anyway, and a uniform error there is confusing.

True concurrency is not simulated here — the test suite shares one session
per test. The concurrency guards are exercised structurally instead:
UNIQUE(family_id, coupon_id) has its own IntegrityError test in
test_plan_credit_service.py, and the redemption cap is a predicated UPDATE
whose 0-row path is covered by test_exhausted_code_is_invalid.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.plan_credit import Coupon, PlanCreditGrant
from app.services.coupon_service import (
    CouponAlreadyRedeemed,
    CouponInvalid,
    CouponService,
)


def test_normalize_uppercases_and_trims():
    assert CouponService.normalize_code("  lanzamiento ") == "LANZAMIENTO"


def test_normalize_rejects_empty():
    with pytest.raises(CouponInvalid):
        CouponService.normalize_code("   ")


async def _coupon(db, **overrides):
    values = {
        "code": "LANZAMIENTO",
        "kind": "launch",
        "tier": "plus",
        "duration_days": 30,
    }
    values.update(overrides)
    row = Coupon(**values)
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_redeem_grants_credit_and_counts_the_redemption(
    db_session, test_family
):
    coupon = await _coupon(db_session)

    redeemed, grant = await CouponService.redeem(
        db_session, family_id=test_family.id, code="lanzamiento"
    )

    assert redeemed.id == coupon.id
    assert grant.tier == "plus"
    assert grant.source == "coupon"
    assert grant.coupon_id == coupon.id
    assert grant.ends_at - grant.starts_at == timedelta(days=30)

    await db_session.refresh(coupon)
    assert coupon.redemption_count == 1


@pytest.mark.asyncio
async def test_redeem_a_lifetime_coupon(db_session, test_family):
    await _coupon(db_session, code="FUNDADOR", kind="comp", tier="pro",
                  duration_days=None)

    _, grant = await CouponService.redeem(
        db_session, family_id=test_family.id, code="FUNDADOR"
    )
    assert grant.ends_at is None
    assert grant.tier == "pro"


@pytest.mark.asyncio
async def test_unknown_code_is_invalid(db_session, test_family):
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="NOPE"
        )


@pytest.mark.asyncio
async def test_inactive_code_is_invalid(db_session, test_family):
    await _coupon(db_session, is_active=False)
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )


@pytest.mark.asyncio
async def test_not_yet_valid_code_is_invalid(db_session, test_family):
    await _coupon(
        db_session, valid_from=datetime.now(timezone.utc) + timedelta(days=1)
    )
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )


@pytest.mark.asyncio
async def test_expired_code_is_invalid(db_session, test_family):
    await _coupon(
        db_session, valid_until=datetime.now(timezone.utc) - timedelta(days=1)
    )
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )


@pytest.mark.asyncio
async def test_exhausted_code_is_invalid(db_session, test_family, sample_family):
    await _coupon(db_session, max_redemptions=1)

    await CouponService.redeem(
        db_session, family_id=sample_family.id, code="LANZAMIENTO"
    )
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )


@pytest.mark.asyncio
async def test_second_redemption_by_the_same_family_is_rejected(
    db_session, test_family
):
    await _coupon(db_session)

    await CouponService.redeem(
        db_session, family_id=test_family.id, code="LANZAMIENTO"
    )
    with pytest.raises(CouponAlreadyRedeemed):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )

    grants = (
        await db_session.execute(
            select(PlanCreditGrant).where(
                PlanCreditGrant.family_id == test_family.id
            )
        )
    ).scalars().all()
    assert len(grants) == 1


@pytest.mark.asyncio
async def test_exhausted_coupon_does_not_over_count(
    db_session, test_family, sample_family
):
    """The counter must never exceed max_redemptions, even after a rejected
    attempt — a failed redeem that still incremented would silently burn a
    seat."""
    coupon = await _coupon(db_session, max_redemptions=1)

    await CouponService.redeem(
        db_session, family_id=sample_family.id, code="LANZAMIENTO"
    )
    with pytest.raises(CouponInvalid):
        await CouponService.redeem(
            db_session, family_id=test_family.id, code="LANZAMIENTO"
        )

    await db_session.refresh(coupon)
    assert coupon.redemption_count == 1


@pytest.mark.asyncio
async def test_two_coupons_stack(db_session, test_family):
    await _coupon(db_session, code="UNO")
    await _coupon(db_session, code="DOS")

    _, first = await CouponService.redeem(
        db_session, family_id=test_family.id, code="UNO"
    )
    _, second = await CouponService.redeem(
        db_session, family_id=test_family.id, code="DOS"
    )

    assert second.starts_at == first.ends_at
    assert second.ends_at - first.starts_at == timedelta(days=60)
