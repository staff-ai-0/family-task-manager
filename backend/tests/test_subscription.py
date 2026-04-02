"""
Tests for subscription models, UsageService, and premium gating.
"""
import pytest
import pytest_asyncio
from datetime import date, datetime, timezone

from fastapi import HTTPException

from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking
from app.services.usage_service import UsageService
from app.core.premium import get_family_plan, require_feature, FamilyPlan, DEFAULT_FREE_LIMITS


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
