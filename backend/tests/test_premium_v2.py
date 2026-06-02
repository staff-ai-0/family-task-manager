"""Tests for scanner-v2 premium feature flags.

Covers:
  - a2a_webhook blocked on free plan (plus required)
  - fx_cross_charge allowed on pro plan
  - Regression: free-tier user with USD receipt on MXN account is routed to
    HITL drafts queue, not auto-FX-converted (Spec §10 + T9 spec review).
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from app.core.premium import FamilyPlan, DEFAULT_FREE_LIMITS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def free_user(db, family):
    """A PARENT user whose family is on the free plan (no active subscription).

    Plan is resolved via monkeypatching get_family_plan in each test — this
    fixture only creates the User row so require_feature has a valid user arg.
    """
    from app.models.user import User, UserRole
    u = User(
        email="free-plan-user@test.example",
        name="Free User",
        role=UserRole.PARENT,
        family_id=family.id,
        email_verified=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def pro_user(db, family):
    """A PARENT user whose family will be patched onto the pro plan."""
    from app.models.user import User, UserRole
    u = User(
        email="pro-plan-user@test.example",
        name="Pro User",
        role=UserRole.PARENT,
        family_id=family.id,
        email_verified=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def _free_plan(family_id=None) -> FamilyPlan:
    """Return a FamilyPlan representing the free tier."""
    return FamilyPlan(
        name="free",
        limits=dict(DEFAULT_FREE_LIMITS),
        status="active",
        family_id=family_id,
    )


def _pro_plan(family_id=None) -> FamilyPlan:
    """Return a FamilyPlan representing the pro tier."""
    return FamilyPlan(
        name="pro",
        limits={
            **DEFAULT_FREE_LIMITS,
            "budget_reports": True,
            "budget_goals": True,
            "csv_import": True,
            "ai_features": True,
            "max_receipt_scans_per_month": -1,
            "max_recurring_transactions": -1,
            "max_budget_transactions_per_month": -1,
            "max_family_members": -1,
            "max_budget_accounts": -1,
            "max_gigs_per_month": -1,
            "a2a_webhook": True,
            "item_trends": True,
            "fx_cross_charge": True,
        },
        status="active",
        family_id=family_id,
    )


def _plus_plan(family_id=None) -> FamilyPlan:
    """Return a FamilyPlan representing the plus tier."""
    return FamilyPlan(
        name="plus",
        limits={
            **DEFAULT_FREE_LIMITS,
            "budget_reports": True,
            "budget_goals": True,
            "csv_import": True,
            "ai_features": True,
            "max_receipt_scans_per_month": -1,
            "max_recurring_transactions": -1,
            "max_budget_transactions_per_month": -1,
            "max_family_members": -1,
            "max_budget_accounts": -1,
            "max_gigs_per_month": -1,
            "a2a_webhook": True,
            "item_trends": True,
            "fx_cross_charge": False,
        },
        status="active",
        family_id=family_id,
    )


# ---------------------------------------------------------------------------
# Plan flag tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_plan_blocks_a2a_webhook(db, free_user, monkeypatch):
    """Free plan must not allow a2a_webhook (requires plus)."""
    from app.core.premium import require_feature

    monkeypatch.setattr(
        "app.core.premium.get_family_plan",
        AsyncMock(return_value=_free_plan(free_user.family_id)),
    )

    with pytest.raises(Exception) as exc_info:
        await require_feature("a2a_webhook", db, free_user)

    # Should be an HTTP 403
    exc = exc_info.value
    assert hasattr(exc, "status_code"), (
        f"Expected HTTPException, got {type(exc).__name__}: {exc}"
    )
    assert exc.status_code == 403
    assert exc.detail["error"] == "upgrade_required"
    assert exc.detail["feature"] == "a2a_webhook"
    assert exc.detail["plan_needed"] == "plus"


@pytest.mark.asyncio
async def test_pro_plan_allows_fx_cross_charge(db, pro_user, monkeypatch):
    """Pro plan must allow fx_cross_charge (no exception raised)."""
    from app.core.premium import require_feature

    monkeypatch.setattr(
        "app.core.premium.get_family_plan",
        AsyncMock(return_value=_pro_plan(pro_user.family_id)),
    )

    # Must not raise
    plan = await require_feature("fx_cross_charge", db, pro_user)
    assert plan.name == "pro"


# ---------------------------------------------------------------------------
# Regression: Spec §10 — free-tier currency mismatch routes to drafts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_free_user_currency_mismatch_routes_to_drafts(
    db, family, free_user, account_factory, monkeypatch,
):
    """Spec §10 + T9 spec review: free-tier users with a USD receipt on an MXN
    account must be routed to the HITL drafts queue (not auto-FX-converted).
    """
    from datetime import date
    from app.services.budget.receipt_scanner_service import scan_and_create_transaction

    mxn = await account_factory(family.id, name="MXN cash", currency="MXN")

    fake_receipt = MagicMock(
        date=date(2026, 5, 28),
        total_amount=-4200,
        payee_name="WALMART US",
        currency="USD",
        card_last4=None,
        iva_cents=None,
        confidence=0.92,
        items=[],
        raw_text="",
    )

    async def fake_scan(_b, _t, model=None):
        return fake_receipt

    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.scan_receipt", fake_scan,
    )

    # Patch get_family_plan in the scanner service module to return free plan.
    # is_feature_enabled() resolves it via get_family_plan, so patching at
    # the scanner module level is sufficient.
    monkeypatch.setattr(
        "app.services.budget.receipt_scanner_service.get_family_plan",
        AsyncMock(return_value=_free_plan(family.id)),
    )

    result = await scan_and_create_transaction(
        db=db,
        family_id=family.id,
        user_id=free_user.id,
        account_id=mxn.id,
        image_bytes=b"x",
        media_type="image/jpeg",
        force=False,
    )

    assert result["success"] is False
    assert result["transaction_id"] is None
    assert result.get("draft_id") is not None, (
        f"Expected draft_id to be set, got result={result!r}"
    )
    assert "currency_mismatch" in (result.get("message") or ""), (
        f"Expected 'currency_mismatch' in message, got: {result.get('message')!r}"
    )
