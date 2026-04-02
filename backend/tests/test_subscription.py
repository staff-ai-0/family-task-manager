"""
Tests for subscription models: SubscriptionPlan, FamilySubscription, UsageTracking.
"""
import pytest
from datetime import date, datetime, timezone

from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking


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
