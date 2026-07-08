"""End-to-end tests for feature gating on protected routes.

Verifies that `require_feature()` raises 403 with structured
`detail.error="upgrade_required"` BEFORE business-logic side effects
happen on routes guarded by the premium gate.

The fixtures here build a free plan with the specific limit-key set to
zero (numeric) or False (boolean) per test, since the test_parent_user
in conftest has no active subscription — `get_family_plan()` falls back
to the DB free plan, then to DEFAULT_FREE_LIMITS if absent.
"""
import pytest
import pytest_asyncio
from datetime import date
from httpx import AsyncClient

from app.models.subscription import SubscriptionPlan


@pytest_asyncio.fixture
async def free_plan_no_ai(db_session):
    """Free plan with receipt_scan + ai_features fully blocked."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits={
            "max_family_members": 4,
            "max_budget_accounts": 2,
            "max_budget_transactions_per_month": 30,
            "max_recurring_transactions": 0,
            "budget_reports": False,
            "budget_goals": False,
            "csv_import": False,
            "max_receipt_scans_per_month": 0,
            "ai_features": False,
        },
        sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def free_plan_zero_txns(db_session):
    """Free plan that allows ZERO budget transactions per month."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits={
            "max_family_members": 4,
            "max_budget_accounts": 2,
            "max_budget_transactions_per_month": 0,
            "max_recurring_transactions": 0,
            "budget_reports": False,
            "budget_goals": False,
            "csv_import": False,
            "max_receipt_scans_per_month": 0,
            "ai_features": False,
        },
        sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def free_plan_zero_members(db_session):
    """Free plan with family_member quota of zero (no invites)."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits={
            "max_family_members": 0,
            "max_budget_accounts": 2,
            "max_budget_transactions_per_month": 30,
            "max_recurring_transactions": 0,
            "budget_reports": False,
            "budget_goals": False,
            "csv_import": False,
            "max_receipt_scans_per_month": 0,
            "ai_features": False,
        },
        sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest_asyncio.fixture
async def free_plan_no_reports(db_session):
    """Free plan with budget_reports=False (boolean lock)."""
    plan = SubscriptionPlan(
        name="free",
        display_name="Free",
        display_name_es="Gratis",
        price_monthly_cents=0,
        price_annual_cents=0,
        limits={
            "max_family_members": 4,
            "max_budget_accounts": 2,
            "max_budget_transactions_per_month": 30,
            "max_recurring_transactions": 0,
            "budget_reports": False,
            "budget_goals": False,
            "csv_import": False,
            "max_receipt_scans_per_month": 0,
            "ai_features": False,
        },
        sort_order=0,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest.mark.asyncio
async def test_receipt_scan_blocked_for_free_plan(
    client: AsyncClient, free_plan_no_ai, auth_headers
):
    """Free plan blocks /scan-receipt before reading the upload body.

    With ai_features=False the gate fires before the file is consumed,
    so the test does not need a real image — only the multipart
    structure must satisfy FastAPI's request parser.
    """
    resp = await client.post(
        "/api/budget/transactions/scan-receipt",
        files={"file": ("receipt.jpg", b"fakeimg", "image/jpeg")},
        data={"account_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    # Either gate (ai_features OR receipt_scan) may fire first depending
    # on order in the handler; both are valid blocks for this plan.
    assert body["detail"]["feature"] in ("receipt_scan", "ai_features")


@pytest.mark.asyncio
async def test_budget_transaction_blocked_when_quota_zero(
    client: AsyncClient, db_session, test_family, free_plan_zero_txns, auth_headers
):
    """POST /api/budget/transactions/ returns 403 when monthly quota = 0."""
    # Need a real account_id since the schema requires UUID; the gate
    # fires inside the handler AFTER schema parsing but BEFORE the
    # service is touched, so providing a syntactically valid UUID is
    # enough.
    from app.models.budget import BudgetAccount
    account = BudgetAccount(
        family_id=test_family.id, name="Test Checking",
        type="checking", starting_balance=0,
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    resp = await client.post(
        "/api/budget/transactions/",
        json={
            "account_id": str(account.id),
            "date": date.today().isoformat(),
            "amount": -1000,
            "notes": "test",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "budget_transaction"


@pytest.mark.asyncio
async def test_invitation_send_blocked_when_family_member_quota_zero(
    client: AsyncClient, test_family, free_plan_zero_members, auth_headers
):
    """POST /api/invitations/send returns 403 when family_member quota = 0."""
    resp = await client.post(
        "/api/invitations/send",
        json={
            "email": "newkid@example.com",
            "family_id": str(test_family.id),
            "role": "child",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "family_member"


@pytest.mark.asyncio
async def test_spending_report_blocked_on_free_plan(
    client: AsyncClient, free_plan_no_reports, auth_headers
):
    """GET /api/budget/reports/spending returns 403 when budget_reports=False."""
    resp = await client.get(
        "/api/budget/reports/spending",
        params={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "budget_reports"


@pytest.mark.asyncio
async def test_goals_list_blocked_on_free_plan(
    client: AsyncClient, free_plan_no_reports, auth_headers
):
    """GET /api/budget/goals/ returns 403 when budget_goals=False.

    Reuses free_plan_no_reports because budget_goals is also False
    in that plan; both boolean flags travel together on free.
    """
    resp = await client.get("/api/budget/goals/", headers=auth_headers)
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "budget_goals"


# ---------------------------------------------------------------------------
# WS-F1: AI endpoints (Jarvis chat/stream, calendar scanner) must be plan-gated
# on ai_features — before this, any Free-tier parent had unbounded LLM spend.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def plus_plan_with_ai(db_session, test_family):
    """Plus plan with ai_features=True + an active subscription for test_family."""
    from app.models.subscription import FamilySubscription

    plan = SubscriptionPlan(
        name="plus",
        display_name="Plus",
        display_name_es="Plus",
        price_monthly_cents=9900,
        price_annual_cents=99000,
        limits={
            "max_family_members": 8,
            "max_budget_accounts": 10,
            "max_budget_transactions_per_month": -1,
            "max_recurring_transactions": 10,
            "budget_reports": True,
            "budget_goals": True,
            "csv_import": True,
            "max_receipt_scans_per_month": 50,
            "ai_features": True,
        },
        sort_order=1,
    )
    db_session.add(plan)
    await db_session.flush()
    sub = FamilySubscription(
        family_id=test_family.id,
        plan_id=plan.id,
        billing_cycle="monthly",
        status="active",
    )
    db_session.add(sub)
    await db_session.commit()
    return plan


@pytest.mark.asyncio
async def test_jarvis_chat_blocked_for_free_plan(
    client: AsyncClient, free_plan_no_ai, auth_headers
):
    """POST /api/jarvis/chat returns 403 upgrade_required on ai_features=False."""
    resp = await client.post(
        "/api/jarvis/chat", json={"message": "hola"}, headers=auth_headers
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "ai_features"


@pytest.mark.asyncio
async def test_jarvis_chat_stream_blocked_for_free_plan(
    client: AsyncClient, free_plan_no_ai, auth_headers
):
    """POST /api/jarvis/chat-stream 403s BEFORE the SSE stream starts."""
    resp = await client.post(
        "/api/jarvis/chat-stream", json={"message": "hola"}, headers=auth_headers
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "ai_features"


@pytest.mark.asyncio
async def test_calendar_scan_document_blocked_for_free_plan(
    client: AsyncClient, free_plan_no_ai, auth_headers
):
    """POST /api/calendar/scan-document 403s before touching the upload."""
    resp = await client.post(
        "/api/calendar/scan-document",
        files={"file": ("flyer.jpg", b"fakeimg", "image/jpeg")},
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["detail"]["error"] == "upgrade_required"
    assert body["detail"]["feature"] == "ai_features"


@pytest.mark.asyncio
async def test_jarvis_chat_passes_gate_on_plus_plan(
    client: AsyncClient, plus_plan_with_ai, auth_headers, monkeypatch
):
    """With an active plus subscription (ai_features=True) the plan gate opens.

    LITELLM_API_KEY is blanked so the service raises its 'not configured'
    ValidationError → the route maps it to 502. Reaching 502 (not 403)
    proves the request got PAST the premium gate.
    """
    from app.core import config

    monkeypatch.setattr(config.settings, "LITELLM_API_KEY", "")
    resp = await client.post(
        "/api/jarvis/chat", json={"message": "hola"}, headers=auth_headers
    )
    assert resp.status_code == 502, resp.text
