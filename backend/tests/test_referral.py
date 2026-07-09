"""Tests for the referral program (give-a-month/get-a-month).

Covers: code generation + uniqueness, referral recorded once, self-referral
rejected, double-referral rejected, reward applied to BOTH families (both
the internal-credit path and the paid-sub extension path), family isolation,
the end-to-end register-family ?ref=CODE flow, and the /api/referrals/me
route.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.premium import get_family_plan_by_id
from app.models.family import Family
from app.models.referral import Referral
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.services.referral_service import (
    REFERRAL_REWARD_DAYS,
    ReferralService,
    generate_referral_code,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PLUS_LIMITS = {
    "max_family_members": 6,
    "max_budget_accounts": 10,
    "max_budget_transactions_per_month": -1,
    "max_recurring_transactions": -1,
    "budget_reports": True,
    "budget_goals": True,
    "csv_import": True,
    "max_receipt_scans_per_month": 50,
    "ai_features": True,
}


@pytest_asyncio.fixture
async def plus_plan(db_session):
    """An active 'plus' plan so internal credits resolve to Plus."""
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        currency="MXN",
        price_monthly_cents=9900,
        price_annual_cents=99000,
        limits=dict(_PLUS_LIMITS),
        sort_order=10,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def referrer_family(db_session):
    fam = Family(name="Referrer Family", referral_code="REFERONE")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    return fam


@pytest_asyncio.fixture
async def referred_family(db_session):
    fam = Family(name="Referred Family")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    return fam


async def _sub_for(db_session, family_id):
    return (
        await db_session.execute(
            select(FamilySubscription).where(
                FamilySubscription.family_id == family_id
            )
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Code generation + uniqueness
# ---------------------------------------------------------------------------

def test_generate_referral_code_shape():
    code = generate_referral_code()
    assert len(code) == 8
    assert code.isupper() or code.isdigit() or code.isalnum()
    # No ambiguous characters (0/O/1/I/L excluded from the alphabet).
    for ch in code:
        assert ch in "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def test_generate_referral_code_varies():
    codes = {generate_referral_code() for _ in range(200)}
    # Astronomically unlikely to collide across 200 draws of a 31^8 space.
    assert len(codes) > 190


@pytest.mark.asyncio
async def test_get_or_create_referral_code_is_stable(db_session, referred_family):
    """First call generates + persists; second returns the SAME code."""
    code1 = await ReferralService.get_or_create_referral_code(
        db_session, referred_family.id
    )
    assert code1 and len(code1) == 8
    code2 = await ReferralService.get_or_create_referral_code(
        db_session, referred_family.id
    )
    assert code2 == code1
    # Persisted on the row.
    refreshed = (
        await db_session.execute(
            select(Family).where(Family.id == referred_family.id)
        )
    ).scalar_one()
    assert refreshed.referral_code == code1


@pytest.mark.asyncio
async def test_two_families_get_distinct_codes(
    db_session, referrer_family, referred_family
):
    # referrer already has a preset code; give the referred one lazily.
    c2 = await ReferralService.get_or_create_referral_code(
        db_session, referred_family.id
    )
    assert referrer_family.referral_code != c2


@pytest.mark.asyncio
async def test_get_family_by_referral_code_case_insensitive(
    db_session, referrer_family
):
    found = await ReferralService.get_family_by_referral_code(
        db_session, "referone"
    )
    assert found is not None and found.id == referrer_family.id
    # Unknown code → None.
    assert (
        await ReferralService.get_family_by_referral_code(db_session, "NOPE0000")
    ) is None
    # Empty → None.
    assert await ReferralService.get_family_by_referral_code(db_session, "") is None


# ---------------------------------------------------------------------------
# Recording + reward
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_referral_recorded_once_and_rewards_both(
    db_session, plus_plan, referrer_family, referred_family
):
    ref = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_family.id
    )
    assert ref is not None
    assert ref.reward_granted_at is not None

    # Exactly one referral row.
    rows = (
        await db_session.execute(
            select(Referral).where(
                Referral.referred_family_id == referred_family.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1

    # BOTH families now resolve to Plus.
    ref_plan = await get_family_plan_by_id(db_session, referrer_family.id)
    red_plan = await get_family_plan_by_id(db_session, referred_family.id)
    assert ref_plan.name == "plus"
    assert red_plan.name == "plus"

    # The credit lives on families.referral_bonus_until (~30 days out) — NOT
    # on a subscription row — so the PayPal reconcile sweep can never erase it.
    for fam_id in (referrer_family.id, referred_family.id):
        fam = (
            await db_session.execute(select(Family).where(Family.id == fam_id))
        ).scalar_one()
        assert fam.referral_bonus_until is not None
        end = fam.referral_bonus_until
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        days = (end - datetime.now(timezone.utc)).days
        assert 28 <= days <= REFERRAL_REWARD_DAYS
        # No self-expiring subscription row is created for a free referrer.
        assert await _sub_for(db_session, fam_id) is None


@pytest.mark.asyncio
async def test_self_referral_rejected(db_session, plus_plan, referrer_family):
    ref = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referrer_family.id
    )
    assert ref is None
    # No referral row, no credit.
    rows = (await db_session.execute(select(Referral))).scalars().all()
    assert rows == []
    assert await _sub_for(db_session, referrer_family.id) is None
    fam = (
        await db_session.execute(
            select(Family).where(Family.id == referrer_family.id)
        )
    ).scalar_one()
    assert fam.referral_bonus_until is None


@pytest.mark.asyncio
async def test_double_referral_rejected(
    db_session, plus_plan, referrer_family, referred_family
):
    first = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_family.id
    )
    assert first is not None
    # Capture the referred family's credit after the first (only) reward.
    fam1 = (
        await db_session.execute(
            select(Family).where(Family.id == referred_family.id)
        )
    ).scalar_one()
    bonus_after_first = fam1.referral_bonus_until
    assert bonus_after_first is not None

    # A SECOND family tries to claim the same referred family.
    other_referrer = Family(name="Other Referrer", referral_code="OTHERREF")
    db_session.add(other_referrer)
    await db_session.commit()

    second = await ReferralService.record_referral_and_reward(
        db_session, other_referrer.id, referred_family.id
    )
    assert second is None

    # Still exactly one referral row; the credit was NOT stacked again.
    rows = (
        await db_session.execute(
            select(Referral).where(
                Referral.referred_family_id == referred_family.id
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    await db_session.refresh(fam1)
    assert fam1.referral_bonus_until == bonus_after_first
    # The second referrer got NO credit.
    other = (
        await db_session.execute(
            select(Family).where(Family.id == other_referrer.id)
        )
    ).scalar_one()
    assert other.referral_bonus_until is None
    assert await _sub_for(db_session, other_referrer.id) is None


@pytest.mark.asyncio
async def test_unknown_code_resolves_to_none_no_referral(db_session, plus_plan):
    fam = await ReferralService.get_family_by_referral_code(db_session, "ZZZZ9999")
    assert fam is None
    assert (await db_session.execute(select(Referral))).scalars().all() == []


@pytest.mark.asyncio
async def test_paid_sub_left_untouched_credit_on_family(
    db_session, plus_plan, referrer_family, referred_family
):
    """A referrer on a live PAID sub keeps their PayPal row COMPLETELY
    untouched (no clobbered period, no severed linkage). The reward lands on
    families.referral_bonus_until, stacked to begin after the paid period."""
    now = datetime.now(timezone.utc)
    paid = FamilySubscription(
        family_id=referrer_family.id,
        plan_id=plus_plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-PAIDSUB123",
        current_period_start=now,
        current_period_end=now + timedelta(days=10),
    )
    db_session.add(paid)
    await db_session.commit()

    ref = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_family.id
    )
    assert ref is not None

    subs = (
        await db_session.execute(
            select(FamilySubscription).where(
                FamilySubscription.family_id == referrer_family.id
            )
        )
    ).scalars().all()
    # Still exactly one row — and every PayPal-linked column is untouched.
    assert len(subs) == 1
    sub = subs[0]
    assert sub.paypal_subscription_id == "I-PAIDSUB123"  # untouched
    assert sub.cancel_at_period_end is False  # not converted to a credit
    end = sub.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    # Paid period is UNCHANGED (~10 days) — the sweep-clobbered field is safe.
    assert 9 <= (end - now).days <= 11

    # The reward is on the family row, stacked after the paid period: ~40 days.
    fam = (
        await db_session.execute(
            select(Family).where(Family.id == referrer_family.id)
        )
    ).scalar_one()
    assert fam.referral_bonus_until is not None
    bonus = fam.referral_bonus_until
    if bonus.tzinfo is None:
        bonus = bonus.replace(tzinfo=timezone.utc)
    # 10 (paid remaining) + 30 (reward) ≈ 40 days out.
    assert 38 <= (bonus - now).days <= 41
    # Still resolves to Plus (via the live paid sub).
    assert (await get_family_plan_by_id(db_session, referrer_family.id)).name == "plus"


@pytest.mark.asyncio
async def test_paid_sub_referral_bonus_survives_reconcile(
    db_session, plus_plan, referrer_family, referred_family, monkeypatch
):
    """Regression: the nightly PayPal reconcile sweep must NOT erase a paid
    referrer's reward.

    The old bug wrote the +30d onto current_period_end; reconcile then
    overwrote it from PayPal's next_billing_at (which knows nothing of the
    internal credit), zeroing the reward within 24h. Now the credit lives on
    families.referral_bonus_until, which reconcile never touches.
    """
    from app.jobs import subscription_sweep
    from app.services.paypal_service import PayPalService

    now = datetime.now(timezone.utc)
    paid = FamilySubscription(
        family_id=referrer_family.id,
        plan_id=plus_plan.id,
        billing_cycle="monthly",
        status="active",
        paypal_subscription_id="I-PAIDSUB999",
        current_period_start=now,
        current_period_end=now + timedelta(days=10),
    )
    db_session.add(paid)
    await db_session.commit()

    ref = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_family.id
    )
    assert ref is not None

    fam = (
        await db_session.execute(
            select(Family).where(Family.id == referrer_family.id)
        )
    ).scalar_one()
    bonus_before = fam.referral_bonus_until
    assert bonus_before is not None
    if bonus_before.tzinfo is None:
        bonus_before = bonus_before.replace(tzinfo=timezone.utc)

    # PayPal reports the ORIGINAL next_billing (no knowledge of the +30d), and
    # we make it DIFFER from the local period so reconcile actively rewrites
    # current_period_end — proving the sweep runs and WOULD have clobbered a
    # period-end-based credit.
    paypal_next = now + timedelta(days=15)

    def fake_get_subscription(subscription_id):
        return {
            "subscription_id": subscription_id,
            "status": "ACTIVE",
            "plan_id": "P-XYZ",
            "next_billing_at": paypal_next.isoformat(),
        }

    monkeypatch.setattr(
        PayPalService, "get_subscription", staticmethod(fake_get_subscription)
    )

    changed = await subscription_sweep.reconcile_with_paypal(db_session)
    assert changed == 1  # reconcile did rewrite the period from PayPal

    # Period reconciled to PayPal's value (day 15)...
    await db_session.refresh(paid)
    end = paid.current_period_end
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    assert abs((end - paypal_next).total_seconds()) < 60

    # ...but the referral credit SURVIVED untouched on the family row.
    await db_session.refresh(fam)
    survived = fam.referral_bonus_until
    assert survived is not None
    if survived.tzinfo is None:
        survived = survived.replace(tzinfo=timezone.utc)
    assert abs((survived - bonus_before).total_seconds()) < 1


@pytest.mark.asyncio
async def test_no_plus_plan_credit_recorded_but_resolves_free(
    db_session, referrer_family, referred_family
):
    """With no Plus plan configured the referral is still recorded and the
    credit timestamp is stamped, but it gracefully resolves to free until a
    Plus plan exists — and no subscription row is ever created."""
    ref = await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_family.id
    )
    assert ref is not None
    assert await _sub_for(db_session, referrer_family.id) is None
    assert await _sub_for(db_session, referred_family.id) is None
    for fam_id in (referrer_family.id, referred_family.id):
        fam = (
            await db_session.execute(select(Family).where(Family.id == fam_id))
        ).scalar_one()
        # Credit timestamp is stamped (harmless — resolves to Plus once a Plus
        # plan is configured)...
        assert fam.referral_bonus_until is not None
        # ...but with no Plus plan it resolves to free right now.
        assert (await get_family_plan_by_id(db_session, fam_id)).name == "free"


# ---------------------------------------------------------------------------
# Family isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_count_successful_referrals_is_family_scoped(
    db_session, plus_plan, referrer_family
):
    # referrer_family refers two families; a THIRD unrelated family refers one.
    referred_a = Family(name="A")
    referred_b = Family(name="B")
    other = Family(name="Other", referral_code="OTHERXYZ")
    referred_c = Family(name="C")
    db_session.add_all([referred_a, referred_b, other, referred_c])
    await db_session.commit()

    await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_a.id
    )
    await ReferralService.record_referral_and_reward(
        db_session, referrer_family.id, referred_b.id
    )
    await ReferralService.record_referral_and_reward(
        db_session, other.id, referred_c.id
    )

    assert (
        await ReferralService.count_successful_referrals(
            db_session, referrer_family.id
        )
        == 2
    )
    assert (
        await ReferralService.count_successful_referrals(db_session, other.id) == 1
    )


# ---------------------------------------------------------------------------
# End-to-end: register-family with ?ref=CODE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_family_with_ref_records_and_rewards(
    client, db_session, plus_plan, referrer_family
):
    resp = await client.post(
        "/api/auth/register-family",
        json={
            "email": "founder-ref@test.com",
            "name": "Founder",
            "password": "password123",
            "family_name": "Newly Founded Family",
            "accept_terms": True,
            "ref": referrer_family.referral_code,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    new_family_id = resp.json()["user"]["family_id"]

    # A referral row links referrer → the new family.
    ref_row = (
        await db_session.execute(
            select(Referral).where(
                Referral.referrer_family_id == referrer_family.id,
                Referral.referred_family_id == new_family_id,
            )
        )
    ).scalar_one_or_none()
    assert ref_row is not None
    assert ref_row.reward_granted_at is not None

    # Both families are now on Plus.
    assert (await get_family_plan_by_id(db_session, referrer_family.id)).name == "plus"
    assert (await get_family_plan_by_id(db_session, new_family_id)).name == "plus"


@pytest.mark.asyncio
async def test_register_family_with_bad_ref_still_succeeds(
    client, db_session, plus_plan
):
    """An unknown ?ref code must not break signup; just no referral."""
    resp = await client.post(
        "/api/auth/register-family",
        json={
            "email": "founder-badref@test.com",
            "name": "Founder",
            "password": "password123",
            "family_name": "No Ref Family",
            "accept_terms": True,
            "ref": "DOESNOTEXIST",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    assert (await db_session.execute(select(Referral))).scalars().all() == []


@pytest.mark.asyncio
async def test_join_by_code_ignores_ref(client, db_session, test_family, plus_plan):
    """A join-by-code signup (not founding a family) must NOT create a
    referral even if a ref is passed — you can't be referred by joining."""
    # Give the target family a join code + a distinct referrer.
    test_family.join_code = "JOINME"
    referrer = Family(name="Ref", referral_code="ABCDWXYZ")
    db_session.add(referrer)
    await db_session.commit()

    resp = await client.post(
        "/api/auth/register-family",
        json={
            "email": "kid-ref@test.com",
            "name": "Kid",
            "password": "password123",
            "family_code": "JOINME",
            "role": "child",
            "accept_terms": True,
            "ref": "ABCDWXYZ",
        },
    )
    assert resp.status_code in (200, 201), resp.text
    assert (await db_session.execute(select(Referral))).scalars().all() == []


# ---------------------------------------------------------------------------
# /api/referrals/me route
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_referrals_me_route(client, auth_headers, db_session, test_family):
    resp = await client.get("/api/referrals/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] and len(body["code"]) == 8
    assert body["reward_days"] == REFERRAL_REWARD_DAYS
    assert body["joined_count"] == 0
    assert f"/register?ref={body['code']}" in body["share_link"]


@pytest.mark.asyncio
async def test_referrals_me_requires_parent(client, db_session, test_child_user):
    """A CHILD cannot view the referral surface (parent-only)."""
    login = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    token = login.json()["access_token"]
    resp = await client.get(
        "/api/referrals/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403, resp.text
