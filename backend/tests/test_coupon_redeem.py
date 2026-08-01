"""Coupon redemption rules.

Error contract: every reason a code is unusable (unknown, inactive, not yet
valid, expired, exhausted) raises the SAME CouponInvalid, so the endpoint is
not an oracle for which codes exist. Only already-redeemed is distinct — the
family can see that state anyway, and a uniform error there is confusing.

Concurrency IS simulated for the one contract that demands it: two genuinely
independent sessions racing CouponService.redeem() for the same code and the
same family (test_concurrent_redeem_same_family_awards_exactly_once below),
following the same async_sessionmaker + asyncio.gather(..., return_exceptions
=True) pattern as test_gig_claim_race.py, test_cash_concurrency.py,
test_allocation_race.py and test_task_assignment_race.py. Everything else in
this file — the validation matrix, the cap's 0-row path, the pre-check's
IntegrityError-equivalent behavior — stays single-session, since those
branches don't depend on two transactions actually overlapping in time.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


@pytest.mark.asyncio
async def test_concurrent_redeem_same_family_awards_exactly_once(
    test_engine, db_session, test_family
):
    """Two independent sessions redeem the SAME code for the SAME family at
    the same time. Deterministic, not timing-dependent: PlanCreditService.
    grant() takes a per-family pg_advisory_xact_lock, so the two attempts
    fully serialize — whichever one acquires the lock second only does so
    after the first has committed, and by then a conflicting
    PlanCreditGrant row already exists, so its own INSERT unconditionally
    hits UNIQUE(family_id, coupon_id) at flush. This is exactly the branch
    the widened try/except (wrapping grant() as well as commit()) exists to
    convert into CouponAlreadyRedeemed instead of a raw IntegrityError."""
    coupon = await _coupon(db_session)
    coupon_id = coupon.id
    family_id = test_family.id

    maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _redeem():
        async with maker() as s:
            return await CouponService.redeem(
                s, family_id=family_id, code="LANZAMIENTO"
            )

    results = await asyncio.gather(_redeem(), _redeem(), return_exceptions=True)

    succeeded = [r for r in results if isinstance(r, tuple)]
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(succeeded) == 1, f"expected 1 success, got {results}"
    assert len(failed) == 1 and isinstance(failed[0], CouponAlreadyRedeemed), (
        f"expected 1 CouponAlreadyRedeemed, got {results}"
    )

    grants = (
        await db_session.execute(
            select(PlanCreditGrant).where(
                PlanCreditGrant.family_id == family_id,
                PlanCreditGrant.coupon_id == coupon_id,
            )
        )
    ).scalars().all()
    assert len(grants) == 1, f"expected exactly 1 grant row, got {len(grants)}"

    await db_session.refresh(coupon)
    assert coupon.redemption_count == 1
