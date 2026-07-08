"""
Tests for subscription models, UsageService, and premium gating.
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking
from app.services.usage_service import UsageService
from app.core.premium import get_family_plan, require_feature, FamilyPlan, DEFAULT_FREE_LIMITS


@pytest.fixture(autouse=True)
def _mute_email_transport():
    """Billing state transitions dispatch emails; never hit SMTP in tests."""
    with patch(
        "app.services.email_service.EmailService._send",
        new=AsyncMock(return_value=True),
    ):
        yield


# ---------------------------------------------------------------------------
# Plan fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def free_plan(db_session):
    """Create a free plan in the DB."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits=dict(DEFAULT_FREE_LIMITS),
        sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def plus_plan(db_session):
    """Create a Plus plan in the DB."""
    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=499,
        price_annual_cents=4990,
        limits={
            "max_family_members": 8,
            "max_budget_accounts": 10,
            "max_budget_transactions_per_month": -1,
            "max_recurring_transactions": 20,
            "budget_reports": True,
            "budget_goals": True,
            "csv_import": True,
            "max_receipt_scans_per_month": 15,
            "ai_features": False,
        },
        sort_order=1,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest.mark.asyncio
async def test_create_subscription_plan(db_session):
    """Create a subscription plan with JSONB limits and verify all fields."""
    limits = {
        "max_family_members": 10,
        "max_task_templates": 50,
        "budget_enabled": True,
    }
    plan = SubscriptionPlan(
        name="premium",
        display_name="Premium",
        display_name_es="Premium",
        price_monthly_cents=499,
        price_annual_cents=4990,
        limits=limits,
        sort_order=1,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)

    assert plan.id is not None
    assert plan.name == "premium"
    assert plan.display_name == "Premium"
    assert plan.display_name_es == "Premium"
    assert plan.price_monthly_cents == 499
    assert plan.price_annual_cents == 4990
    assert plan.limits["max_family_members"] == 10
    assert plan.limits["budget_enabled"] is True
    assert plan.is_active is True
    assert plan.sort_order == 1
    assert plan.created_at is not None
    assert plan.updated_at is not None


@pytest.mark.asyncio
async def test_create_family_subscription(db_session, test_family):
    """Create a family subscription linked to a family and plan, verify fields."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits={"max_family_members": 4},
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)

    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
        current_period_start=now,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    assert sub.id is not None
    assert sub.family_id == test_family.id
    assert sub.plan_id == plan.id
    assert sub.billing_cycle == "monthly"
    assert sub.status == "active"
    assert sub.current_period_start is not None
    assert sub.current_period_end is None
    assert sub.cancelled_at is None
    assert sub.paypal_subscription_id is None
    assert sub.created_at is not None


@pytest.mark.asyncio
async def test_create_usage_tracking(db_session, test_family):
    """Create a usage tracking record and verify count/feature."""
    usage = UsageTracking(
        family_id=test_family.id,
        feature="task_templates_created",
        period_start=date(2026, 4, 1),
        count=5,
    )
    db_session.add(usage)
    await db_session.commit()
    await db_session.refresh(usage)

    assert usage.id is not None
    assert usage.family_id == test_family.id
    assert usage.feature == "task_templates_created"
    assert usage.period_start == date(2026, 4, 1)
    assert usage.count == 5
    assert usage.created_at is not None


# ---------------------------------------------------------------------------
# UsageService tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_usage_returns_zero_when_no_record(db_session, test_family):
    """get_usage should return 0 when there is no tracking record."""
    count = await UsageService.get_usage(db_session, test_family.id, "budget_transaction")
    assert count == 0


@pytest.mark.asyncio
async def test_increment_creates_record_and_returns_count(db_session, test_family):
    """increment should create a record on first call and increment on subsequent calls."""
    first = await UsageService.increment(db_session, test_family.id, "budget_transaction")
    assert first == 1

    second = await UsageService.increment(db_session, test_family.id, "budget_transaction")
    assert second == 2


@pytest.mark.asyncio
async def test_check_limit_allows_under_limit(db_session, test_family):
    """check_limit should return True when usage is below the limit."""
    allowed = await UsageService.check_limit(db_session, test_family.id, "budget_transaction", 10)
    assert allowed is True


@pytest.mark.asyncio
async def test_check_limit_denies_at_limit(db_session, test_family):
    """check_limit should return False when usage equals the limit."""
    usage = UsageTracking(
        family_id=test_family.id,
        feature="receipt_scan",
        period_start=date.today().replace(day=1),
        count=15,
    )
    db_session.add(usage)
    await db_session.commit()

    allowed = await UsageService.check_limit(db_session, test_family.id, "receipt_scan", 15)
    assert allowed is False


@pytest.mark.asyncio
async def test_check_limit_unlimited_always_allows(db_session, test_family):
    """check_limit with limit=-1 should always return True regardless of count."""
    usage = UsageTracking(
        family_id=test_family.id,
        feature="budget_transaction",
        period_start=date.today().replace(day=1),
        count=9999,
    )
    db_session.add(usage)
    await db_session.commit()

    allowed = await UsageService.check_limit(db_session, test_family.id, "budget_transaction", -1)
    assert allowed is True


# ---------------------------------------------------------------------------
# Premium gating tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_family_plan_defaults_to_free(db_session, test_parent_user):
    """Without any subscription, get_family_plan should return free plan defaults."""
    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "free"
    assert plan.limits["max_family_members"] == 4
    assert plan.limits["budget_reports"] is False


@pytest.mark.asyncio
async def test_get_family_plan_returns_active_subscription(
    db_session, test_family, test_parent_user, plus_plan
):
    """An active Plus subscription should return plus plan limits."""
    sub = FamilySubscription(
        family_id=test_family.id,
        plan_id=plus_plan.id,
        billing_cycle="monthly",
        status="active",
    )
    db_session.add(sub)
    await db_session.commit()

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "plus"
    assert plan.limits["budget_reports"] is True
    assert plan.limits["max_family_members"] == 8


@pytest.mark.asyncio
async def test_require_feature_allows_boolean_feature(
    db_session, test_family, test_parent_user, plus_plan
):
    """Plus plan should allow boolean features like budget_reports."""
    sub = FamilySubscription(
        family_id=test_family.id,
        plan_id=plus_plan.id,
        billing_cycle="monthly",
        status="active",
    )
    db_session.add(sub)
    await db_session.commit()

    plan = await require_feature("budget_reports", db_session, test_parent_user)
    assert plan.name == "plus"


@pytest.mark.asyncio
async def test_require_feature_denies_boolean_feature_on_free(
    db_session, test_parent_user
):
    """Free plan should deny budget_reports with HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        await require_feature("budget_reports", db_session, test_parent_user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "upgrade_required"
    assert exc_info.value.detail["feature"] == "budget_reports"


@pytest.mark.asyncio
async def test_require_feature_denies_numeric_at_limit(
    db_session, test_family, test_parent_user, plus_plan
):
    """Plus plan should deny receipt_scan when usage is at the limit (15/15)."""
    sub = FamilySubscription(
        family_id=test_family.id,
        plan_id=plus_plan.id,
        billing_cycle="monthly",
        status="active",
    )
    db_session.add(sub)
    await db_session.commit()

    # Seed usage at the limit
    usage = UsageTracking(
        family_id=test_family.id,
        feature="receipt_scan",
        period_start=date.today().replace(day=1),
        count=15,
    )
    db_session.add(usage)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await require_feature("receipt_scan", db_session, test_parent_user)

    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["error"] == "upgrade_required"
    assert detail["current_usage"] == 15
    assert detail["limit"] == 15


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pro_plan(db_session):
    """Create a Pro plan in the DB."""
    plan = SubscriptionPlan(
        name="pro",
        display_name="Pro",
        display_name_es="Pro",
        price_monthly_cents=999,
        price_annual_cents=9990,
        limits={
            "max_family_members": -1,
            "max_budget_accounts": -1,
            "max_budget_transactions_per_month": -1,
            "max_recurring_transactions": -1,
            "budget_reports": True,
            "budget_goals": True,
            "csv_import": True,
            "max_receipt_scans_per_month": -1,
            "ai_features": True,
        },
        sort_order=2,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest.mark.asyncio
async def test_list_plans_endpoint(client, auth_headers, free_plan, plus_plan, pro_plan):
    """GET /api/subscriptions/plans should return all active plans sorted by sort_order."""
    response = await client.get("/api/subscriptions/plans", headers=auth_headers)
    assert response.status_code == 200

    plans = response.json()
    assert len(plans) == 3
    assert plans[0]["name"] == "free"
    assert plans[1]["name"] == "plus"
    assert plans[2]["name"] == "pro"
    # Verify structure
    assert "limits" in plans[0]
    assert "price_monthly_cents" in plans[0]
    assert "display_name_es" in plans[0]


@pytest.mark.asyncio
async def test_get_current_returns_free_by_default(client, auth_headers):
    """GET /api/subscriptions/current with no subscription should return free plan info."""
    response = await client.get("/api/subscriptions/current", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["plan_name"] == "free"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_get_usage_endpoint(client, auth_headers):
    """GET /api/subscriptions/usage should return usage for numeric features."""
    response = await client.get("/api/subscriptions/usage", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    # Should contain numeric features like budget_transaction
    features = [item["feature"] for item in data]
    assert "budget_transaction" in features
    # Should NOT contain boolean features like budget_reports
    assert "budget_reports" not in features
    # Each item should have the right structure
    for item in data:
        assert "feature" in item
        assert "current" in item
        assert "limit" in item
        assert "period" in item


@pytest.mark.asyncio
async def test_cancel_without_subscription_returns_404(client, auth_headers):
    """POST /api/subscriptions/cancel with no active subscription should return 404."""
    response = await client.post("/api/subscriptions/cancel", headers=auth_headers)
    assert response.status_code == 404
    assert "No active subscription" in response.json()["detail"]


@pytest.mark.asyncio
async def test_transaction_create_blocked_at_limit(
    client, auth_headers, db_session, test_family, free_plan
):
    from app.models.budget import BudgetAccount
    account = BudgetAccount(
        family_id=test_family.id, name="Test Checking",
        type="checking", starting_balance=0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    # Max out usage
    from app.models.subscription import UsageTracking
    from datetime import date
    usage = UsageTracking(
        family_id=test_family.id, feature="budget_transaction",
        period_start=date.today().replace(day=1), count=30,
    )
    db_session.add(usage)
    await db_session.commit()

    response = await client.post(
        "/api/budget/transactions/",
        headers=auth_headers,
        json={
            "account_id": str(account.id),
            "date": date.today().isoformat(),
            "amount": -5000,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "upgrade_required"


# ---------------------------------------------------------------------------
# Billing robustness (WS-E): dunning grace, recovery, checkout guard,
# join-code cap
# ---------------------------------------------------------------------------


async def _make_paid_sub(
    db_session, family, plan, *, status="active", paypal_id="I-OLD-SUB",
    payment_failure_at=None, current_period_end=None,
):
    sub = FamilySubscription(
        family_id=family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status=status,
        paypal_subscription_id=paypal_id,
        payment_failure_at=payment_failure_at,
        current_period_end=current_period_end,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


@pytest.mark.asyncio
async def test_payment_failed_within_grace_keeps_plan(
    db_session, test_family, test_parent_user, plus_plan
):
    """A payment_failed sub inside the grace window keeps paid entitlements."""
    await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="payment_failed",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "plus"
    assert plan.status == "payment_failed"
    assert plan.limits["budget_reports"] is True


@pytest.mark.asyncio
async def test_payment_failed_after_grace_resolves_to_free(
    db_session, test_family, test_parent_user, plus_plan
):
    """Once payment_failure_at + BILLING_GRACE_DAYS passes, the family is free
    even before the sweep stamps the final status."""
    from app.core.config import settings

    await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="payment_failed",
        payment_failure_at=(
            datetime.now(timezone.utc)
            - timedelta(days=settings.BILLING_GRACE_DAYS + 2)
        ),
    )

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "free"


@pytest.mark.asyncio
async def test_sweep_downgrades_grace_expired_only(
    db_session, test_family, sample_family, plus_plan
):
    """The sweep stamps grace_expired on subs past the window and leaves
    in-grace subs untouched."""
    from app.core.config import settings
    from app.jobs.subscription_sweep import downgrade_grace_expired_subscriptions

    expired = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="payment_failed", paypal_id="I-EXPIRED-GRACE",
        payment_failure_at=(
            datetime.now(timezone.utc)
            - timedelta(days=settings.BILLING_GRACE_DAYS + 1)
        ),
    )
    in_grace = await _make_paid_sub(
        db_session, sample_family, plus_plan,
        status="payment_failed", paypal_id="I-IN-GRACE",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(hours=6),
    )

    n = await downgrade_grace_expired_subscriptions(db_session)
    assert n == 1
    await db_session.refresh(expired)
    await db_session.refresh(in_grace)
    assert expired.status == "grace_expired"
    assert in_grace.status == "payment_failed"


@pytest.mark.asyncio
async def test_payment_completed_recovers_failed_sub(
    db_session, test_family, plus_plan
):
    """PAYMENT.SALE.COMPLETED on a payment_failed sub flips it back to active,
    clears the failure marker and advances the period."""
    from app.services.subscription_state import apply_payment_completed

    sub = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="payment_failed", paypal_id="I-RECOVER",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(days=1),
        current_period_end=datetime.now(timezone.utc) - timedelta(days=1),
    )

    result = await apply_payment_completed(db_session, "I-RECOVER")
    assert result is not None
    await db_session.refresh(sub)
    assert sub.status == "active"
    assert sub.payment_failure_at is None
    period_end = sub.current_period_end
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)
    assert period_end > datetime.now(timezone.utc) + timedelta(days=25)


@pytest.mark.asyncio
async def test_payment_completed_advances_renewal_period_end(
    db_session, test_family, plus_plan
):
    """A renewal payment on an ACTIVE sub advances current_period_end by one
    cycle instead of leaving it frozen at activation+30d."""
    from app.services.subscription_state import apply_payment_completed

    old_end = datetime.now(timezone.utc) + timedelta(hours=2)
    sub = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="active", paypal_id="I-RENEW",
        current_period_end=old_end,
    )

    await apply_payment_completed(db_session, "I-RENEW")
    await db_session.refresh(sub)
    new_end = sub.current_period_end
    if new_end.tzinfo is None:
        new_end = new_end.replace(tzinfo=timezone.utc)
    assert new_end > old_end + timedelta(days=29)


@pytest.mark.asyncio
async def test_checkout_does_not_clobber_active_subscription(
    client, auth_headers, db_session, test_family, plus_plan, pro_plan
):
    """Starting an upgrade checkout must stage the new plan in pending_*
    columns and leave the live (paying) subscription row untouched."""
    pro_plan.paypal_plan_id_monthly = "P-PRO-MONTHLY"
    await db_session.commit()

    live = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="active", paypal_id="I-LIVE-PLUS",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )

    with patch(
        "app.services.paypal_service.PayPalService.create_subscription",
        return_value={
            "subscription_id": "I-NEW-PRO",
            "approval_url": "https://paypal.example/approve",
            "status": "APPROVAL_PENDING",
        },
    ):
        resp = await client.post(
            "/api/subscriptions/checkout",
            headers=auth_headers,
            json={"plan_name": "pro", "billing_cycle": "monthly"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["paypal_subscription_id"] == "I-NEW-PRO"

    await db_session.refresh(live)
    # Live entitlement untouched — an abandoned checkout costs nothing.
    assert live.status == "active"
    assert live.plan_id == plus_plan.id
    assert live.paypal_subscription_id == "I-LIVE-PLUS"
    # New checkout staged for /activate to promote.
    assert live.pending_plan_id == pro_plan.id
    assert live.pending_billing_cycle == "monthly"
    assert live.pending_paypal_subscription_id == "I-NEW-PRO"


@pytest.mark.asyncio
async def test_activate_promotes_staged_checkout_and_cancels_old(
    client, auth_headers, db_session, test_family, plus_plan, pro_plan
):
    """/activate on a staged plan change swaps in the new plan and cancels
    the superseded PayPal subscription."""
    live = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="active", paypal_id="I-LIVE-PLUS",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )
    live.pending_plan_id = pro_plan.id
    live.pending_billing_cycle = "monthly"
    live.pending_paypal_subscription_id = "I-NEW-PRO"
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.execute_subscription",
        return_value={"status": "ACTIVE", "subscription_id": "I-NEW-PRO"},
    ), patch(
        "app.services.paypal_service.PayPalService.cancel_subscription",
        return_value={"status": "cancelled", "subscription_id": "I-LIVE-PLUS"},
    ) as mock_cancel:
        resp = await client.post(
            "/api/subscriptions/activate",
            headers=auth_headers,
            json={"paypal_subscription_id": "I-NEW-PRO"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "activated"
    assert body["plan_name"] == "pro"

    await db_session.refresh(live)
    assert live.status == "active"
    assert live.plan_id == pro_plan.id
    assert live.paypal_subscription_id == "I-NEW-PRO"
    assert live.pending_plan_id is None
    assert live.pending_billing_cycle is None
    assert live.pending_paypal_subscription_id is None
    # Superseded PayPal sub cancelled — no double billing.
    mock_cancel.assert_called_once()
    assert mock_cancel.call_args[0][0] == "I-LIVE-PLUS"


@pytest.mark.asyncio
async def test_checkout_from_grace_expired_stages_pending(
    client, auth_headers, db_session, test_family, plus_plan, pro_plan
):
    """Regression (whole-PR review, MAJOR 3): a re-checkout from
    grace_expired must NOT overwrite paypal_subscription_id in place — the
    old PayPal sub may still be retrying charges. It must be staged in the
    pending_* columns so /activate cancels the old sub."""
    pro_plan.paypal_plan_id_monthly = "P-PRO-MONTHLY"
    await db_session.commit()

    old = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="grace_expired", paypal_id="I-OLD-GRACE",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(days=30),
    )

    with patch(
        "app.services.paypal_service.PayPalService.create_subscription",
        return_value={
            "subscription_id": "I-NEW-PRO",
            "approval_url": "https://paypal.example/approve",
            "status": "APPROVAL_PENDING",
        },
    ):
        resp = await client.post(
            "/api/subscriptions/checkout",
            headers=auth_headers,
            json={"plan_name": "pro", "billing_cycle": "monthly"},
        )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(old)
    # Old (possibly still billing) PayPal sub id preserved, not clobbered.
    assert old.paypal_subscription_id == "I-OLD-GRACE"
    assert old.status == "grace_expired"
    assert old.plan_id == plus_plan.id
    # New checkout staged for /activate to promote (and cancel the old sub).
    assert old.pending_plan_id == pro_plan.id
    assert old.pending_billing_cycle == "monthly"
    assert old.pending_paypal_subscription_id == "I-NEW-PRO"


@pytest.mark.asyncio
async def test_activate_from_grace_expired_cancels_old_paypal_sub(
    client, auth_headers, db_session, test_family, plus_plan, pro_plan
):
    """The staged re-checkout from grace_expired goes live on /activate and
    the superseded (still retrying) PayPal sub is cancelled."""
    old = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="grace_expired", paypal_id="I-OLD-GRACE",
        payment_failure_at=datetime.now(timezone.utc) - timedelta(days=30),
    )
    old.pending_plan_id = pro_plan.id
    old.pending_billing_cycle = "monthly"
    old.pending_paypal_subscription_id = "I-NEW-PRO"
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.execute_subscription",
        return_value={"status": "ACTIVE", "subscription_id": "I-NEW-PRO"},
    ), patch(
        "app.services.paypal_service.PayPalService.cancel_subscription",
        return_value={"status": "cancelled", "subscription_id": "I-OLD-GRACE"},
    ) as mock_cancel:
        resp = await client.post(
            "/api/subscriptions/activate",
            headers=auth_headers,
            json={"paypal_subscription_id": "I-NEW-PRO"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "activated"

    await db_session.refresh(old)
    assert old.status == "active"
    assert old.plan_id == pro_plan.id
    assert old.paypal_subscription_id == "I-NEW-PRO"
    assert old.payment_failure_at is None
    assert old.pending_paypal_subscription_id is None
    mock_cancel.assert_called_once()
    assert mock_cancel.call_args[0][0] == "I-OLD-GRACE"


@pytest.mark.asyncio
async def test_activate_flags_review_when_supersede_cancel_fails(
    client, auth_headers, db_session, test_family, plus_plan, pro_plan
):
    """Regression (whole-PR review, MAJOR 2): when cancelling the superseded
    PayPal sub fails, the activation still succeeds but the row is flagged
    needs_review with the old sub id in review_reason — a persistent trace of
    the double-billing risk."""
    live = await _make_paid_sub(
        db_session, test_family, plus_plan,
        status="active", paypal_id="I-LIVE-PLUS",
        current_period_end=datetime.now(timezone.utc) + timedelta(days=20),
    )
    live.pending_plan_id = pro_plan.id
    live.pending_billing_cycle = "monthly"
    live.pending_paypal_subscription_id = "I-NEW-PRO"
    await db_session.commit()

    with patch(
        "app.services.paypal_service.PayPalService.execute_subscription",
        return_value={"status": "ACTIVE", "subscription_id": "I-NEW-PRO"},
    ), patch(
        "app.services.paypal_service.PayPalService.cancel_subscription",
        side_effect=RuntimeError("paypal down"),
    ):
        resp = await client.post(
            "/api/subscriptions/activate",
            headers=auth_headers,
            json={"paypal_subscription_id": "I-NEW-PRO"},
        )
    # Activation must NOT fail because of the cancel failure.
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "activated"

    await db_session.refresh(live)
    assert live.status == "active"
    assert live.paypal_subscription_id == "I-NEW-PRO"
    # Persistent operator trace of the un-cancelled old sub.
    assert live.needs_review is True
    assert "I-LIVE-PLUS" in (live.review_reason or "")


@pytest.mark.asyncio
async def test_join_code_register_rejected_at_member_cap(
    client, db_session, sample_family
):
    """Join-by-code must enforce the plan's family_member limit (free = 4)."""
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole

    for i in range(4):  # free plan default max_family_members = 4
        db_session.add(User(
            email=f"member{i}@cap-test.example.com",
            password_hash=get_password_hash("password123"),
            name=f"Member {i}",
            role=UserRole.PARENT if i == 0 else UserRole.CHILD,
            family_id=sample_family.id,
            points=0,
            is_active=True,
        ))
    await db_session.commit()

    resp = await client.post(
        "/api/auth/register-family",
        json={
            "email": "fifth@cap-test.example.com",
            "password": "password123",
            "name": "Fifth Member",
            "family_code": "ABCDEF",
            "preferred_lang": "en",
        },
    )
    assert resp.status_code == 403
    assert "member limit" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_join_code_register_allowed_under_cap(
    client, db_session, sample_family
):
    """Under the cap, join-by-code still works."""
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole

    db_session.add(User(
        email="solo-parent@cap-test.example.com",
        password_hash=get_password_hash("password123"),
        name="Solo Parent",
        role=UserRole.PARENT,
        family_id=sample_family.id,
        points=0,
        is_active=True,
    ))
    await db_session.commit()

    resp = await client.post(
        "/api/auth/register-family",
        json={
            "email": "second@cap-test.example.com",
            "password": "password123",
            "name": "Second Member",
            "family_code": "ABCDEF",
            "preferred_lang": "en",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["email"] == "second@cap-test.example.com"
