# Premium Subscription System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Free/Plus/Pro subscription system with PayPal billing, usage tracking, and feature gating to the Family Task Manager.

**Architecture:** Three new database tables (`subscription_plans`, `family_subscriptions`, `usage_tracking`) with an Alembic migration. A `premium.py` module provides FastAPI dependencies (`get_family_plan`, `require_feature`) that existing routes add to gate features. PayPal Subscriptions API handles billing. Frontend gets a subscription management page and an upgrade prompt component.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, PayPal Subscriptions API, Astro 5, Tailwind CSS v4

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `backend/app/models/subscription.py` | SQLAlchemy models: SubscriptionPlan, FamilySubscription, UsageTracking |
| `backend/app/schemas/subscription.py` | Pydantic schemas for API request/response |
| `backend/app/services/subscription_service.py` | Business logic: plan lookup, subscription CRUD, PayPal integration |
| `backend/app/services/usage_service.py` | Usage tracking: get, increment, check limit |
| `backend/app/core/premium.py` | FastAPI dependencies: `get_family_plan`, `require_feature` |
| `backend/app/api/routes/subscriptions.py` | API endpoints: plans, checkout, activate, cancel, usage, webhook |
| `backend/tests/test_subscription.py` | Tests for subscription models, services, and endpoints |
| `frontend/src/pages/parent/settings/subscription.astro` | Subscription management page |
| `frontend/src/components/UpgradePrompt.astro` | Reusable upgrade prompt shown on 403 |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/main.py` | Register subscriptions router |
| `backend/app/core/config.py` | Add `PAYPAL_PLAN_ID_PLUS_MONTHLY`, `PAYPAL_PLAN_ID_PLUS_ANNUAL`, `PAYPAL_PLAN_ID_PRO_MONTHLY`, `PAYPAL_PLAN_ID_PRO_ANNUAL` |
| `backend/app/api/routes/budget/transactions.py` | Add `require_feature("budget_transaction")` to POST |
| `backend/app/api/routes/budget/reports.py` | Add `require_feature("budget_reports")` to GET endpoints |
| `backend/app/api/routes/budget/goals.py` | Add `require_feature("budget_goals")` to POST/PUT |
| `backend/app/api/routes/budget/recurring_transactions.py` | Add `require_feature("recurring_transaction")` to POST |
| `backend/tests/conftest.py` | Add subscription-related fixtures |
| `backend/seed_data.py` | Add plan seeding and demo subscription |
| `frontend/src/middleware.ts` | Fetch and pass plan info to `context.locals` |

---

### Task 1: Subscription Models + Migration

**Files:**
- Create: `backend/app/models/subscription.py`
- Modify: `backend/tests/conftest.py` (add enum types)
- Test: `backend/tests/test_subscription.py`

- [ ] **Step 1: Create the subscription models file**

```python
# backend/app/models/subscription.py
"""
Subscription models for premium tier system.

Tables: subscription_plans, family_subscriptions, usage_tracking
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class SubscriptionPlan(Base):
    """Available subscription plans (Free, Plus, Pro)."""

    __tablename__ = "subscription_plans"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name_es: Mapped[str] = mapped_column(String(100), nullable=False)
    price_monthly_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    price_annual_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paypal_plan_id_monthly: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    paypal_plan_id_annual: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    subscriptions: Mapped[list["FamilySubscription"]] = relationship(
        "FamilySubscription", back_populates="plan"
    )


class FamilySubscription(Base):
    """Active subscription for a family. One per family."""

    __tablename__ = "family_subscriptions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    plan_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False)  # "monthly" | "annual"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # active | past_due | cancelled | expired
    paypal_subscription_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    current_period_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    plan: Mapped["SubscriptionPlan"] = relationship(
        "SubscriptionPlan", back_populates="subscriptions"
    )
    family: Mapped["Family"] = relationship("Family", backref="subscription")


class UsageTracking(Base):
    """Tracks per-feature usage counts per month per family."""

    __tablename__ = "usage_tracking"
    __table_args__ = (
        UniqueConstraint("family_id", "feature", "period_start", name="uq_usage_family_feature_period"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature: Mapped[str] = mapped_column(String(50), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [ ] **Step 2: Write tests for the models**

```python
# backend/tests/test_subscription.py
"""Tests for the premium subscription system."""
import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking


FREE_LIMITS = {
    "max_family_members": 4,
    "max_budget_accounts": 2,
    "max_budget_transactions_per_month": 30,
    "max_recurring_transactions": 0,
    "budget_reports": False,
    "budget_goals": False,
    "csv_import": False,
    "max_receipt_scans_per_month": 0,
    "ai_features": False,
}

PLUS_LIMITS = {
    "max_family_members": 8,
    "max_budget_accounts": 5,
    "max_budget_transactions_per_month": 200,
    "max_recurring_transactions": 5,
    "budget_reports": True,
    "budget_goals": True,
    "csv_import": True,
    "max_receipt_scans_per_month": 15,
    "ai_features": True,
}

PRO_LIMITS = {
    "max_family_members": -1,
    "max_budget_accounts": -1,
    "max_budget_transactions_per_month": -1,
    "max_recurring_transactions": -1,
    "budget_reports": True,
    "budget_goals": True,
    "csv_import": True,
    "max_receipt_scans_per_month": -1,
    "ai_features": True,
}


@pytest_asyncio.fixture
async def free_plan(db_session):
    plan = SubscriptionPlan(
        name="free", display_name="Free", display_name_es="Gratis",
        price_monthly_cents=0, price_annual_cents=0,
        limits=FREE_LIMITS, sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def plus_plan(db_session):
    plan = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        price_monthly_cents=500, price_annual_cents=5000,
        limits=PLUS_LIMITS, sort_order=1,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def pro_plan(db_session):
    plan = SubscriptionPlan(
        name="pro", display_name="Pro", display_name_es="Pro",
        price_monthly_cents=1500, price_annual_cents=15000,
        limits=PRO_LIMITS, sort_order=2,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


# --- Model Tests ---

@pytest.mark.asyncio
async def test_create_subscription_plan(db_session):
    plan = SubscriptionPlan(
        name="test", display_name="Test", display_name_es="Prueba",
        price_monthly_cents=999, price_annual_cents=9990,
        limits={"max_family_members": 10}, sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)

    assert plan.id is not None
    assert plan.name == "test"
    assert plan.limits["max_family_members"] == 10
    assert plan.is_active is True


@pytest.mark.asyncio
async def test_create_family_subscription(db_session, test_family, plus_plan):
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)

    assert sub.id is not None
    assert sub.status == "active"
    assert sub.billing_cycle == "monthly"


@pytest.mark.asyncio
async def test_create_usage_tracking(db_session, test_family):
    usage = UsageTracking(
        family_id=test_family.id,
        feature="receipt_scan",
        period_start=date.today().replace(day=1),
        count=5,
    )
    db_session.add(usage)
    await db_session.commit()
    await db_session.refresh(usage)

    assert usage.count == 5
    assert usage.feature == "receipt_scan"
```

- [ ] **Step 3: Run tests to verify models work**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -v`
Expected: 3 tests PASS

- [ ] **Step 4: Generate Alembic migration**

Run: `docker exec family_app_backend alembic revision --autogenerate -m "add subscription tables"`
Then verify the migration file was created and contains the 3 new tables.

- [ ] **Step 5: Apply migration**

Run: `docker exec family_app_backend alembic upgrade head`
Expected: Migration applies without errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/subscription.py backend/tests/test_subscription.py backend/alembic/versions/
git commit -m "feat: add subscription plan, family subscription, and usage tracking models"
```

---

### Task 2: Usage Service

**Files:**
- Create: `backend/app/services/usage_service.py`
- Modify: `backend/tests/test_subscription.py` (add tests)

- [ ] **Step 1: Write failing tests for UsageService**

Add to `backend/tests/test_subscription.py`:

```python
from app.services.usage_service import UsageService


# --- UsageService Tests ---

@pytest.mark.asyncio
async def test_get_usage_returns_zero_when_no_record(db_session, test_family):
    count = await UsageService.get_usage(
        db_session, test_family.id, "receipt_scan", date.today().replace(day=1)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_increment_creates_record_and_returns_count(db_session, test_family):
    count = await UsageService.increment(db_session, test_family.id, "receipt_scan")
    assert count == 1

    count = await UsageService.increment(db_session, test_family.id, "receipt_scan")
    assert count == 2


@pytest.mark.asyncio
async def test_check_limit_allows_under_limit(db_session, test_family):
    allowed = await UsageService.check_limit(
        db_session, test_family.id, "receipt_scan", 15
    )
    assert allowed is True


@pytest.mark.asyncio
async def test_check_limit_denies_at_limit(db_session, test_family):
    # Create usage at the limit
    usage = UsageTracking(
        family_id=test_family.id, feature="receipt_scan",
        period_start=date.today().replace(day=1), count=15,
    )
    db_session.add(usage)
    await db_session.commit()

    allowed = await UsageService.check_limit(
        db_session, test_family.id, "receipt_scan", 15
    )
    assert allowed is False


@pytest.mark.asyncio
async def test_check_limit_unlimited_always_allows(db_session, test_family):
    usage = UsageTracking(
        family_id=test_family.id, feature="receipt_scan",
        period_start=date.today().replace(day=1), count=9999,
    )
    db_session.add(usage)
    await db_session.commit()

    allowed = await UsageService.check_limit(
        db_session, test_family.id, "receipt_scan", -1
    )
    assert allowed is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -k "usage" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.usage_service'`

- [ ] **Step 3: Implement UsageService**

```python
# backend/app/services/usage_service.py
"""
Usage tracking service for premium feature limits.

Tracks how many times a family uses each gated feature per month.
"""
from datetime import date
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import UsageTracking


class UsageService:
    """Manages per-family, per-feature monthly usage counts."""

    @classmethod
    async def get_usage(
        cls, db: AsyncSession, family_id: UUID, feature: str, period: date
    ) -> int:
        """Get current usage count for a feature in a given month."""
        query = select(UsageTracking.count).where(
            and_(
                UsageTracking.family_id == family_id,
                UsageTracking.feature == feature,
                UsageTracking.period_start == period,
            )
        )
        result = await db.execute(query)
        count = result.scalar_one_or_none()
        return count or 0

    @classmethod
    async def increment(
        cls, db: AsyncSession, family_id: UUID, feature: str
    ) -> int:
        """Increment usage count for current month. Creates record if needed. Returns new count."""
        period = date.today().replace(day=1)
        query = select(UsageTracking).where(
            and_(
                UsageTracking.family_id == family_id,
                UsageTracking.feature == feature,
                UsageTracking.period_start == period,
            )
        )
        result = await db.execute(query)
        usage = result.scalar_one_or_none()

        if usage:
            usage.count += 1
        else:
            usage = UsageTracking(
                family_id=family_id,
                feature=feature,
                period_start=period,
                count=1,
            )
            db.add(usage)

        await db.commit()
        await db.refresh(usage)
        return usage.count

    @classmethod
    async def check_limit(
        cls, db: AsyncSession, family_id: UUID, feature: str, limit: int
    ) -> bool:
        """Check if usage is under the limit. limit=-1 means unlimited."""
        if limit == -1:
            return True
        if limit == 0:
            return False
        period = date.today().replace(day=1)
        current = await cls.get_usage(db, family_id, feature, period)
        return current < limit
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -k "usage" -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/usage_service.py backend/tests/test_subscription.py
git commit -m "feat: add UsageService for premium feature usage tracking"
```

---

### Task 3: Premium Gating Dependencies

**Files:**
- Create: `backend/app/core/premium.py`
- Modify: `backend/tests/test_subscription.py` (add tests)

- [ ] **Step 1: Write failing tests for premium dependencies**

Add to `backend/tests/test_subscription.py`:

```python
from app.core.premium import get_family_plan, require_feature, FamilyPlan


# --- Premium Dependency Tests ---

@pytest.mark.asyncio
async def test_get_family_plan_defaults_to_free(db_session, test_parent_user, free_plan):
    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "free"
    assert plan.limits["max_budget_accounts"] == 2


@pytest.mark.asyncio
async def test_get_family_plan_returns_active_subscription(
    db_session, test_parent_user, test_family, plus_plan, free_plan
):
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now, current_period_end=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()

    plan = await get_family_plan(db_session, test_parent_user)
    assert plan.name == "plus"
    assert plan.limits["max_budget_accounts"] == 5


@pytest.mark.asyncio
async def test_require_feature_allows_boolean_feature(
    db_session, test_parent_user, test_family, plus_plan, free_plan
):
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now, current_period_end=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()

    # Should not raise
    await require_feature("budget_reports", db_session, test_parent_user)


@pytest.mark.asyncio
async def test_require_feature_denies_boolean_feature_on_free(
    db_session, test_parent_user, free_plan
):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await require_feature("budget_reports", db_session, test_parent_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "upgrade_required"


@pytest.mark.asyncio
async def test_require_feature_denies_numeric_at_limit(
    db_session, test_parent_user, test_family, plus_plan, free_plan
):
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=test_family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now, current_period_end=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.commit()

    # Max out usage
    usage = UsageTracking(
        family_id=test_family.id, feature="receipt_scan",
        period_start=date.today().replace(day=1), count=15,
    )
    db_session.add(usage)
    await db_session.commit()

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await require_feature("receipt_scan", db_session, test_parent_user)
    assert exc_info.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -k "require_feature or get_family_plan" -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement premium.py**

```python
# backend/app/core/premium.py
"""
Premium feature gating dependencies.

Provides get_family_plan() and require_feature() for use as FastAPI dependencies.
"""
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import User
from app.services.usage_service import UsageService


# Default free-tier limits (used when no plan exists in DB)
DEFAULT_FREE_LIMITS = {
    "max_family_members": 4,
    "max_budget_accounts": 2,
    "max_budget_transactions_per_month": 30,
    "max_recurring_transactions": 0,
    "budget_reports": False,
    "budget_goals": False,
    "csv_import": False,
    "max_receipt_scans_per_month": 0,
    "ai_features": False,
}

# Maps feature names to their limit keys in the JSONB
FEATURE_LIMIT_MAP = {
    "budget_reports": "budget_reports",
    "budget_goals": "budget_goals",
    "csv_import": "csv_import",
    "ai_features": "ai_features",
    "budget_transaction": "max_budget_transactions_per_month",
    "recurring_transaction": "max_recurring_transactions",
    "receipt_scan": "max_receipt_scans_per_month",
    "family_member": "max_family_members",
    "budget_account": "max_budget_accounts",
}

# Features that need the "plus" plan minimum
FEATURE_MIN_PLAN = {
    "budget_reports": "plus",
    "budget_goals": "plus",
    "csv_import": "plus",
    "ai_features": "plus",
    "receipt_scan": "plus",
    "recurring_transaction": "plus",
}


@dataclass
class FamilyPlan:
    """Resolved plan info for a family."""
    name: str
    limits: dict = field(default_factory=dict)
    status: str = "active"
    billing_cycle: str = ""
    family_id: UUID = None


async def get_family_plan(db: AsyncSession, user: User) -> FamilyPlan:
    """Get the effective plan for a user's family. Defaults to free if no subscription."""
    family_id = user.family_id

    # Look for active subscription
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(
            and_(
                FamilySubscription.family_id == family_id,
                FamilySubscription.status.in_(["active", "past_due"]),
            )
        )
    )
    result = await db.execute(query)
    sub = result.scalar_one_or_none()

    if sub and sub.plan:
        return FamilyPlan(
            name=sub.plan.name,
            limits=sub.plan.limits,
            status=sub.status,
            billing_cycle=sub.billing_cycle,
            family_id=family_id,
        )

    # Fall back to "free" plan from DB, or hardcoded defaults
    free_query = select(SubscriptionPlan).where(SubscriptionPlan.name == "free")
    free_result = await db.execute(free_query)
    free_plan = free_result.scalar_one_or_none()

    limits = free_plan.limits if free_plan else DEFAULT_FREE_LIMITS
    return FamilyPlan(
        name="free", limits=limits, status="active", family_id=family_id,
    )


async def require_feature(
    feature: str, db: AsyncSession, user: User
) -> FamilyPlan:
    """
    Check that the user's family plan allows a feature.

    For boolean features: checks limits[key] is True.
    For numeric features: checks usage < limit (limit=-1 means unlimited).
    Raises 403 with upgrade info if denied.
    Returns the FamilyPlan if allowed.
    """
    plan = await get_family_plan(db, user)
    limit_key = FEATURE_LIMIT_MAP.get(feature)

    if not limit_key:
        return plan  # Unknown feature — allow by default

    limit_value = plan.limits.get(limit_key)

    if limit_value is None:
        return plan  # Key not in plan — allow by default

    # Boolean feature
    if isinstance(limit_value, bool):
        if limit_value:
            return plan
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "upgrade_required",
                "feature": feature,
                "plan_needed": FEATURE_MIN_PLAN.get(feature, "plus"),
                "message": f"This feature requires a {FEATURE_MIN_PLAN.get(feature, 'plus').title()} plan.",
            },
        )

    # Numeric feature
    if limit_value == -1:
        return plan  # Unlimited
    if limit_value == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "upgrade_required",
                "feature": feature,
                "plan_needed": FEATURE_MIN_PLAN.get(feature, "plus"),
                "current_usage": 0,
                "limit": 0,
                "message": f"This feature requires a {FEATURE_MIN_PLAN.get(feature, 'plus').title()} plan.",
            },
        )

    # Check usage
    allowed = await UsageService.check_limit(db, plan.family_id, feature, limit_value)
    if allowed:
        return plan

    period = date.today().replace(day=1)
    current = await UsageService.get_usage(db, plan.family_id, feature, period)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "upgrade_required",
            "feature": feature,
            "plan_needed": "pro" if plan.name == "plus" else "plus",
            "current_usage": current,
            "limit": limit_value,
            "message": f"You've reached the {feature.replace('_', ' ')} limit for this month.",
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -v`
Expected: All tests PASS (3 model + 5 usage + 5 premium = 13 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/premium.py backend/tests/test_subscription.py
git commit -m "feat: add premium gating dependencies (get_family_plan, require_feature)"
```

---

### Task 4: Subscription Schemas + API Endpoints

**Files:**
- Create: `backend/app/schemas/subscription.py`
- Create: `backend/app/api/routes/subscriptions.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_subscription.py` (add API tests)

- [ ] **Step 1: Create Pydantic schemas**

```python
# backend/app/schemas/subscription.py
"""Pydantic schemas for subscription endpoints."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    """Public plan info."""
    id: UUID
    name: str
    display_name: str
    display_name_es: str
    price_monthly_cents: int
    price_annual_cents: int
    limits: dict
    sort_order: int

    class Config:
        from_attributes = True


class SubscriptionResponse(BaseModel):
    """Current subscription info."""
    id: UUID
    plan: PlanResponse
    billing_cycle: str
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CheckoutRequest(BaseModel):
    """Request to start subscription checkout."""
    plan_name: str = Field(..., description="Plan name: 'plus' or 'pro'")
    billing_cycle: str = Field(..., description="'monthly' or 'annual'")


class CheckoutResponse(BaseModel):
    """Response with PayPal approval URL."""
    approval_url: str
    paypal_subscription_id: str


class ActivateRequest(BaseModel):
    """Request to activate subscription after PayPal approval."""
    paypal_subscription_id: str


class UsageResponse(BaseModel):
    """Usage info for all tracked features."""
    feature: str
    current: int
    limit: int  # -1 = unlimited, 0 = disabled
    period: str  # YYYY-MM-DD
```

- [ ] **Step 2: Create API route file**

```python
# backend/app/api/routes/subscriptions.py
"""
Subscription management API endpoints.

All endpoints require PARENT role.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.dependencies import require_parent_role
from app.core.premium import get_family_plan, FEATURE_LIMIT_MAP
from app.models.subscription import FamilySubscription, SubscriptionPlan
from app.models.user import User
from app.schemas.subscription import (
    ActivateRequest,
    CheckoutRequest,
    CheckoutResponse,
    PlanResponse,
    SubscriptionResponse,
    UsageResponse,
)
from app.services.usage_service import UsageService

router = APIRouter()


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    """List all active subscription plans."""
    query = (
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/current")
async def get_current_subscription(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Get family's current subscription."""
    plan = await get_family_plan(db, current_user)

    # Get full subscription record if exists
    query = (
        select(FamilySubscription)
        .options(joinedload(FamilySubscription.plan))
        .where(FamilySubscription.family_id == current_user.family_id)
    )
    result = await db.execute(query)
    sub = result.scalar_one_or_none()

    if sub:
        return {
            "id": str(sub.id),
            "plan": {
                "id": str(sub.plan.id),
                "name": sub.plan.name,
                "display_name": sub.plan.display_name,
                "display_name_es": sub.plan.display_name_es,
                "price_monthly_cents": sub.plan.price_monthly_cents,
                "price_annual_cents": sub.plan.price_annual_cents,
                "limits": sub.plan.limits,
                "sort_order": sub.plan.sort_order,
            },
            "billing_cycle": sub.billing_cycle,
            "status": sub.status,
            "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end,
            "cancelled_at": sub.cancelled_at,
        }

    return {
        "id": None,
        "plan": {"name": "free", "display_name": "Free", "limits": plan.limits},
        "billing_cycle": None,
        "status": "active",
        "current_period_start": None,
        "current_period_end": None,
        "cancelled_at": None,
    }


@router.get("/usage", response_model=list[UsageResponse])
async def get_usage(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Get current month's usage for all tracked features."""
    plan = await get_family_plan(db, current_user)
    period = date.today().replace(day=1)
    usage_list = []

    for feature, limit_key in FEATURE_LIMIT_MAP.items():
        limit_value = plan.limits.get(limit_key)
        # Skip boolean features — only show numeric
        if isinstance(limit_value, bool) or limit_value is None:
            continue

        current = await UsageService.get_usage(
            db, current_user.family_id, feature, period
        )
        usage_list.append(UsageResponse(
            feature=feature,
            current=current,
            limit=limit_value,
            period=period.isoformat(),
        ))

    return usage_list


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    data: CheckoutRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Create a PayPal subscription checkout. Returns approval URL."""
    # Validate plan
    query = select(SubscriptionPlan).where(
        SubscriptionPlan.name == data.plan_name,
        SubscriptionPlan.is_active == True,
    )
    result = await db.execute(query)
    plan = result.scalar_one_or_none()

    if not plan or plan.name == "free":
        raise HTTPException(status_code=400, detail="Invalid plan")

    if data.billing_cycle not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Invalid billing cycle")

    paypal_plan_id = (
        plan.paypal_plan_id_monthly
        if data.billing_cycle == "monthly"
        else plan.paypal_plan_id_annual
    )

    if not paypal_plan_id:
        raise HTTPException(
            status_code=400,
            detail="PayPal plan not configured for this billing cycle",
        )

    # TODO: Call PayPal Subscriptions API to create subscription
    # For now, return placeholder — PayPal integration will be wired
    # when PayPal billing plan IDs are configured
    raise HTTPException(
        status_code=501,
        detail="PayPal subscription creation not yet configured. Set PAYPAL_PLAN_ID_* env vars.",
    )


@router.post("/activate")
async def activate_subscription(
    data: ActivateRequest,
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Activate subscription after PayPal approval."""
    # TODO: Verify with PayPal API that subscription is active
    # Create/update FamilySubscription record
    raise HTTPException(
        status_code=501,
        detail="PayPal activation not yet configured.",
    )


@router.post("/cancel")
async def cancel_subscription(
    current_user: User = Depends(require_parent_role),
    db: AsyncSession = Depends(get_db),
):
    """Cancel subscription. Remains active until period end."""
    query = select(FamilySubscription).where(
        FamilySubscription.family_id == current_user.family_id,
        FamilySubscription.status == "active",
    )
    result = await db.execute(query)
    sub = result.scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found")

    from datetime import datetime, timezone
    sub.status = "cancelled"
    sub.cancelled_at = datetime.now(timezone.utc)
    await db.commit()

    return {"message": "Subscription cancelled. Access continues until period end."}
```

- [ ] **Step 3: Register the router in main.py**

Add to `backend/app/main.py` — import and include:

Add this import at the top:
```python
from app.api.routes import subscriptions
```

Add this line after the existing `include_router` calls:
```python
app.include_router(subscriptions.router, prefix="/api/subscriptions", tags=["Subscriptions"])
```

- [ ] **Step 4: Write API tests**

Add to `backend/tests/test_subscription.py`:

```python
# --- API Tests ---

@pytest.mark.asyncio
async def test_list_plans_endpoint(client, free_plan, plus_plan, pro_plan):
    response = await client.get("/api/subscriptions/plans")
    assert response.status_code == 200
    plans = response.json()
    assert len(plans) == 3
    assert plans[0]["name"] == "free"
    assert plans[1]["name"] == "plus"
    assert plans[2]["name"] == "pro"


@pytest.mark.asyncio
async def test_get_current_returns_free_by_default(client, auth_headers, free_plan):
    response = await client.get("/api/subscriptions/current", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["plan"]["name"] == "free"


@pytest.mark.asyncio
async def test_get_usage_endpoint(client, auth_headers, free_plan):
    response = await client.get("/api/subscriptions/usage", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    # Should include numeric features
    features = [u["feature"] for u in data]
    assert "budget_transaction" in features


@pytest.mark.asyncio
async def test_cancel_without_subscription_returns_404(client, auth_headers, free_plan):
    response = await client.post("/api/subscriptions/cancel", headers=auth_headers)
    assert response.status_code == 404
```

- [ ] **Step 5: Run all tests**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -v`
Expected: All tests PASS (13 previous + 4 API = 17 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/subscription.py backend/app/api/routes/subscriptions.py backend/app/main.py backend/tests/test_subscription.py
git commit -m "feat: add subscription API endpoints (plans, current, usage, cancel)"
```

---

### Task 5: Add Config Variables

**Files:**
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Add PayPal plan ID settings**

Add these fields to the `Settings` class in `backend/app/core/config.py`, after the existing PayPal settings block:

```python
    # PayPal Subscription Plan IDs
    PAYPAL_PLAN_ID_PLUS_MONTHLY: str = ""
    PAYPAL_PLAN_ID_PLUS_ANNUAL: str = ""
    PAYPAL_PLAN_ID_PRO_MONTHLY: str = ""
    PAYPAL_PLAN_ID_PRO_ANNUAL: str = ""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/core/config.py
git commit -m "feat: add PayPal subscription plan ID config vars"
```

---

### Task 6: Apply Feature Gates to Existing Budget Endpoints

**Files:**
- Modify: `backend/app/api/routes/budget/transactions.py`
- Modify: `backend/app/api/routes/budget/reports.py`
- Modify: `backend/app/api/routes/budget/goals.py`
- Modify: `backend/app/api/routes/budget/recurring_transactions.py`
- Modify: `backend/tests/test_subscription.py` (add integration test)

- [ ] **Step 1: Read the existing budget route files to find exact function signatures**

Read these files to find the exact `create_transaction`, report endpoints, `create_goal`, and `create_recurring` functions:
- `backend/app/api/routes/budget/transactions.py` (POST endpoint)
- `backend/app/api/routes/budget/reports.py` (GET endpoints)
- `backend/app/api/routes/budget/goals.py` (POST endpoint)
- `backend/app/api/routes/budget/recurring_transactions.py` (POST endpoint)

- [ ] **Step 2: Add gate to transaction creation**

In `backend/app/api/routes/budget/transactions.py`, add the import and call `require_feature` inside the `create_transaction` function body. Add this import at the top:

```python
from app.core.premium import require_feature
```

At the start of the `create_transaction` function body (before any existing logic), add:

```python
    await require_feature("budget_transaction", db, current_user)
```

And after the transaction is successfully created (before the return), add:

```python
    from app.services.usage_service import UsageService
    await UsageService.increment(db, current_user.family_id, "budget_transaction")
```

- [ ] **Step 3: Add gate to budget reports**

In `backend/app/api/routes/budget/reports.py`, add the import and call at the start of each GET endpoint:

```python
from app.core.premium import require_feature
```

At the start of each report function body, add:
```python
    await require_feature("budget_reports", db, current_user)
```

- [ ] **Step 4: Add gate to goals creation**

In `backend/app/api/routes/budget/goals.py`, add the import and call at the start of the POST endpoint:

```python
from app.core.premium import require_feature
```

At the start of the create function body:
```python
    await require_feature("budget_goals", db, current_user)
```

- [ ] **Step 5: Add gate to recurring transaction creation**

In `backend/app/api/routes/budget/recurring_transactions.py`, add the import and call:

```python
from app.core.premium import require_feature
from app.services.usage_service import UsageService
```

At the start of the create function body:
```python
    await require_feature("recurring_transaction", db, current_user)
```

After successful creation:
```python
    await UsageService.increment(db, current_user.family_id, "recurring_transaction")
```

- [ ] **Step 6: Write integration test for gated endpoint**

Add to `backend/tests/test_subscription.py`:

```python
@pytest.mark.asyncio
async def test_transaction_create_blocked_at_limit(
    client, auth_headers, db_session, test_family, free_plan
):
    """Free plan has 30 transaction limit. Verify gating works."""
    # Create an account first
    from app.models.budget import BudgetAccount
    account = BudgetAccount(
        family_id=test_family.id, name="Test Checking",
        type="checking", starting_balance=0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    # Max out usage
    usage = UsageTracking(
        family_id=test_family.id, feature="budget_transaction",
        period_start=date.today().replace(day=1), count=30,
    )
    db_session.add(usage)
    await db_session.commit()

    # Try to create a transaction
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
```

- [ ] **Step 7: Run all tests**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -v`
Expected: All tests PASS (17 previous + 1 integration = 18 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/budget/transactions.py backend/app/api/routes/budget/reports.py backend/app/api/routes/budget/goals.py backend/app/api/routes/budget/recurring_transactions.py backend/tests/test_subscription.py
git commit -m "feat: apply premium feature gates to budget endpoints"
```

---

### Task 7: Seed Data for Plans

**Files:**
- Modify: `backend/seed_data.py`

- [ ] **Step 1: Add plan seeding function and demo subscription**

Add these imports at the top of `backend/seed_data.py`:

```python
from app.models.subscription import SubscriptionPlan, FamilySubscription, UsageTracking
```

Add this function after the existing helper functions:

```python
async def create_subscription_plans(session: AsyncSession):
    """Create the 3 subscription plans."""
    print("\nCreating subscription plans...")

    plans_data = [
        {
            "name": "free", "display_name": "Free", "display_name_es": "Gratis",
            "price_monthly_cents": 0, "price_annual_cents": 0, "sort_order": 0,
            "limits": {
                "max_family_members": 4, "max_budget_accounts": 2,
                "max_budget_transactions_per_month": 30,
                "max_recurring_transactions": 0,
                "budget_reports": False, "budget_goals": False,
                "csv_import": False, "max_receipt_scans_per_month": 0,
                "ai_features": False,
            },
        },
        {
            "name": "plus", "display_name": "Plus", "display_name_es": "Plus",
            "price_monthly_cents": 500, "price_annual_cents": 5000, "sort_order": 1,
            "limits": {
                "max_family_members": 8, "max_budget_accounts": 5,
                "max_budget_transactions_per_month": 200,
                "max_recurring_transactions": 5,
                "budget_reports": True, "budget_goals": True,
                "csv_import": True, "max_receipt_scans_per_month": 15,
                "ai_features": True,
            },
        },
        {
            "name": "pro", "display_name": "Pro", "display_name_es": "Pro",
            "price_monthly_cents": 1500, "price_annual_cents": 15000, "sort_order": 2,
            "limits": {
                "max_family_members": -1, "max_budget_accounts": -1,
                "max_budget_transactions_per_month": -1,
                "max_recurring_transactions": -1,
                "budget_reports": True, "budget_goals": True,
                "csv_import": True, "max_receipt_scans_per_month": -1,
                "ai_features": True,
            },
        },
    ]
    plans = []
    for data in plans_data:
        p = SubscriptionPlan(**data)
        plans.append(p)
    session.add_all(plans)
    await session.commit()
    print(f"  {len(plans)} plans (Free, Plus, Pro)")
    return plans


async def create_demo_subscription(session: AsyncSession, family, plans):
    """Give demo family a Plus subscription so all features are testable."""
    print("\nCreating demo subscription...")
    plus_plan = next(p for p in plans if p.name == "plus")
    now = datetime.now(timezone.utc)
    sub = FamilySubscription(
        family_id=family.id, plan_id=plus_plan.id,
        billing_cycle="monthly", status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    session.add(sub)

    # Add some sample usage
    usage = UsageTracking(
        family_id=family.id, feature="budget_transaction",
        period_start=TODAY.replace(day=1), count=42,
    )
    session.add(usage)
    await session.commit()
    print(f"  Demo family on Plus plan (monthly)")
    return sub
```

Then add calls to these functions in the `main()` function, after the budget section and before the final print:

```python
        # Subscriptions
        plans = await create_subscription_plans(session)
        await create_demo_subscription(session, family, plans)
```

Also add `"usage_tracking"`, `"family_subscriptions"`, `"subscription_plans"` to the `clear_all` tables list (after `"budget_sync_state"` and before `"point_transactions"`).

- [ ] **Step 2: Test the seed script runs**

Run: `docker cp backend/seed_data.py family_app_backend:/app/seed_data.py && docker exec -u root family_app_backend chmod 644 /app/seed_data.py && docker exec -e PYTHONPATH=/app family_app_backend python /app/seed_data.py`
Expected: Output includes "3 plans (Free, Plus, Pro)" and "Demo family on Plus plan"

- [ ] **Step 3: Commit**

```bash
git add backend/seed_data.py
git commit -m "feat: add subscription plan seed data with demo Plus subscription"
```

---

### Task 8: Frontend — Subscription Management Page

**Files:**
- Create: `frontend/src/pages/parent/settings/subscription.astro`
- Modify: `frontend/src/pages/parent/settings/index.astro` (add link)

- [ ] **Step 1: Read existing settings page to understand layout pattern**

Read `frontend/src/pages/parent/settings/index.astro` for the layout import, header style, and navigation pattern.

- [ ] **Step 2: Create subscription management page**

Create `frontend/src/pages/parent/settings/subscription.astro` with:
- Current plan display with name and status badge
- Usage meters for numeric features (transactions, receipt scans)
- Plan comparison table (Free / Plus / Pro) with feature rows
- Upgrade button (links to PayPal checkout — disabled until PayPal plan IDs configured)
- Cancel subscription button (for active paid subscriptions)

The page should:
- Fetch `/api/subscriptions/current` and `/api/subscriptions/usage` and `/api/subscriptions/plans` from the backend
- Use the same layout as other settings pages
- Display amounts in both monthly and annual pricing
- Show the current plan highlighted in the comparison table

- [ ] **Step 3: Add link to subscription page from settings index**

Add a card/link in `frontend/src/pages/parent/settings/index.astro` pointing to `/parent/settings/subscription` with a label like "Suscripción" / "Subscription" and a crown/star icon.

- [ ] **Step 4: Build and verify**

Run: `cd frontend && npx astro build`
Expected: Build passes with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/parent/settings/subscription.astro frontend/src/pages/parent/settings/index.astro
git commit -m "feat: add subscription management page with plan comparison and usage"
```

---

### Task 9: Frontend — UpgradePrompt Component

**Files:**
- Create: `frontend/src/components/UpgradePrompt.astro`

- [ ] **Step 1: Create the upgrade prompt component**

Create `frontend/src/components/UpgradePrompt.astro`:

```astro
---
/**
 * UpgradePrompt Component
 * 
 * Shown when a 403 "upgrade_required" response is received.
 * Displays which feature is locked and links to subscription page.
 *
 * Props:
 * - feature: string - the feature that was blocked
 * - planNeeded: string - the minimum plan required
 * - currentUsage: number | undefined - current usage count (for numeric features)
 * - limit: number | undefined - the limit that was reached
 * - lang: 'en' | 'es' - language
 */

interface Props {
    feature: string;
    planNeeded: string;
    currentUsage?: number;
    limit?: number;
    lang?: 'en' | 'es';
}

const { feature, planNeeded, currentUsage, limit, lang = 'es' } = Astro.props;

const featureNames: Record<string, Record<string, string>> = {
    budget_reports: { en: 'Budget Reports', es: 'Reportes de Presupuesto' },
    budget_goals: { en: 'Budget Goals', es: 'Metas de Presupuesto' },
    csv_import: { en: 'CSV Import', es: 'Importar CSV' },
    receipt_scan: { en: 'Receipt Scanning', es: 'Escaneo de Recibos' },
    budget_transaction: { en: 'Budget Transactions', es: 'Transacciones' },
    recurring_transaction: { en: 'Recurring Transactions', es: 'Transacciones Recurrentes' },
};

const featureLabel = featureNames[feature]?.[lang] ?? feature;
const isLimitReached = currentUsage !== undefined && limit !== undefined;
---

<div class="bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-xl p-6 text-center">
    <div class="text-3xl mb-3">🔒</div>
    <h3 class="text-lg font-bold text-slate-800 mb-2">
        {lang === 'es' ? 'Función Premium' : 'Premium Feature'}
    </h3>
    <p class="text-sm text-slate-600 mb-1">
        <strong>{featureLabel}</strong>
        {lang === 'es' ? ' requiere el plan ' : ' requires the '}
        <span class="font-bold text-blue-600 capitalize">{planNeeded}</span>
    </p>
    {isLimitReached && (
        <p class="text-xs text-slate-500 mb-4">
            {lang === 'es'
                ? `Has usado ${currentUsage} de ${limit} este mes.`
                : `You've used ${currentUsage} of ${limit} this month.`}
        </p>
    )}
    <a
        href="/parent/settings/subscription"
        class="inline-block bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
    >
        {lang === 'es' ? 'Ver Planes' : 'View Plans'}
    </a>
</div>
```

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npx astro build`
Expected: Build passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UpgradePrompt.astro
git commit -m "feat: add UpgradePrompt component for premium feature gating"
```

---

### Task 10: Frontend — Middleware Plan Injection

**Files:**
- Modify: `frontend/src/middleware.ts`

- [ ] **Step 1: Add plan fetching to middleware**

In `frontend/src/middleware.ts`, after the line where `context.locals.user` and `context.locals.token` are set (around line 133-134), add a fetch for the family's subscription plan:

```typescript
            // Fetch family plan for premium gating
            try {
                const planResponse = await fetch(`${apiUrl}/api/subscriptions/current`, {
                    headers: { "Authorization": `Bearer ${token}` },
                });
                if (planResponse.ok) {
                    context.locals.plan = await planResponse.json();
                }
            } catch {
                // Plan fetch failure is non-fatal — default to free
            }
```

This makes `Astro.locals.plan` available in all authenticated pages for conditional rendering of premium features.

- [ ] **Step 2: Build and verify**

Run: `cd frontend && npx astro build`
Expected: Build passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/middleware.ts
git commit -m "feat: inject family plan into Astro locals for premium UI gating"
```

---

### Task 11: Update conftest.py for Subscription Enum Types

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Verify tests pass with new tables**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/test_subscription.py -v`

If tests fail due to missing tables, the `conftest.py` `create_all` call should handle new models automatically since they inherit from `Base`. If there are enum type issues, add any needed enum types to the `enum_types` list in `conftest.py`.

The subscription models don't use custom enums (they use plain strings), so no changes should be needed. Verify by running the full test suite.

- [ ] **Step 2: Run full test suite**

Run: `docker exec -e PYTHONPATH=/app family_app_backend pytest tests/ -v`
Expected: All existing tests + subscription tests pass. No regressions.

- [ ] **Step 3: Commit (if any changes were needed)**

```bash
git add backend/tests/conftest.py
git commit -m "fix: update test conftest for subscription tables"
```
