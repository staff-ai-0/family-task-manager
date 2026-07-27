"""Authorization matrix for the super-admin surface.

The rule under test: an operator needs BOTH users.is_superadmin AND an email
in SUPERADMIN_EMAILS. Either alone is insufficient, and every failure mode
must return 404 (not 403) so the surface is not discoverable.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import require_superadmin
from app.models.user import User


@pytest.mark.asyncio
async def test_require_superadmin_accepts_flag_and_allowlist(
    client: AsyncClient, superadmin_headers: dict
):
    resp = await client.get("/api/admin/ping", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_require_superadmin_rejects_flag_without_allowlist(
    client: AsyncClient, db_session, test_superadmin_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", [])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "superadmin@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_allowlist_without_flag(
    client: AsyncClient, db_session, test_parent_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", ["parent@test.com"])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_plain_parent(
    client: AsyncClient, auth_headers: dict, allowlist_superadmin
):
    resp = await client.get("/api/admin/ping", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_anonymous(client: AsyncClient):
    resp = await client.get("/api/admin/ping")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_family_detail_never_leaks_other_family_members(
    client, db_session, superadmin_headers, test_family
):
    """The operator asks for family A and gets ONLY family A — across every
    tab, not just members.

    Seeds one row in a second family for each of the seven tabs' backing
    queries (members, tasks, budget accounts/transactions/receipt drafts,
    billing, and the a2a webhook + delivery), then asserts none of that
    family's identifiers appear ANYWHERE in the serialized response. This is
    stronger than per-field assertions: it would catch a missing
    `family_id` filter on any of the ten queries in `family_detail`, not
    just the `members` one.
    """
    import json
    from datetime import date

    from app.core.security import get_password_hash
    from app.models.a2a import A2AWebhookDelivery, FamilyA2AWebhook
    from app.models.budget import BudgetAccount, BudgetReceiptDraft, BudgetTransaction
    from app.models.cash_transaction import CashTransaction, CashTransactionType
    from app.models.family import Family
    from app.models.subscription import FamilySubscription, SubscriptionPlan
    from app.models.task_assignment import AssignmentStatus, TaskAssignment
    from app.models.task_template import TaskTemplate
    from app.models.user import User, UserRole

    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    outsider = User(
        email="outsider@test.com",
        password_hash=get_password_hash("password123"),
        name="Outsider",
        role=UserRole.PARENT,
        family_id=other.id,
        email_verified=True,
    )
    db_session.add(outsider)
    await db_session.flush()

    db_session.add(
        CashTransaction(
            user_id=outsider.id,
            family_id=other.id,
            type=CashTransactionType.GIG_EARNED,
            amount_cents=12345,
            balance_before=0,
            balance_after=12345,
        )
    )

    template = TaskTemplate(title="Outsider chore", family_id=other.id)
    db_session.add(template)
    await db_session.flush()

    today = date.today()
    db_session.add(
        TaskAssignment(
            template_id=template.id,
            assigned_to=outsider.id,
            family_id=other.id,
            status=AssignmentStatus.PENDING,
            assigned_date=today,
            week_of=today,
        )
    )

    account = BudgetAccount(
        family_id=other.id, name="Outsider Checking", type="checking", currency="MXN",
    )
    db_session.add(account)
    await db_session.flush()

    txn = BudgetTransaction(
        family_id=other.id, account_id=account.id, date=today, amount=-999,
    )
    db_session.add(txn)
    await db_session.flush()

    db_session.add(
        BudgetReceiptDraft(
            family_id=other.id,
            scanned_data={"total_amount": 9.99},
            confidence=0.1,
            status="pending",
        )
    )

    plan = SubscriptionPlan(
        name="pro", display_name="Pro", display_name_es="Pro",
        currency="USD", price_monthly_cents=1500, price_annual_cents=15000,
    )
    db_session.add(plan)
    await db_session.flush()
    db_session.add(
        FamilySubscription(
            family_id=other.id,
            plan_id=plan.id,
            billing_cycle="monthly",
            status="active",
            paypal_subscription_id="I-OUTSIDER-SUB",
        )
    )

    db_session.add(
        FamilyA2AWebhook(
            family_id=other.id,
            url="https://outsider.example/hook",
            secret="outsider-secret",
            enabled=True,
            last_error="outsider webhook failure",
        )
    )
    db_session.add(
        A2AWebhookDelivery(
            family_id=other.id,
            transaction_id=txn.id,
            payload_json={"a": 1},
            status="pending",
            attempts=0,
        )
    )

    await db_session.commit()

    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=superadmin_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    body_text = json.dumps(body)

    # No identifier belonging to the other family — its id, its member's id
    # or email, its account/transaction ids, or its billing/webhook secrets
    # — may appear anywhere in family A's response.
    assert str(other.id) not in body_text
    assert str(outsider.id) not in body_text
    assert "outsider@test.com" not in body_text
    assert str(template.id) not in body_text
    assert str(account.id) not in body_text
    assert str(txn.id) not in body_text
    assert "I-OUTSIDER-SUB" not in body_text
    assert "outsider-secret" not in body_text
    assert "outsider webhook failure" not in body_text

    # The count-only fields (tasks by_status, budget counts, delivery
    # counts) carry no identifying string, so a leaked cross-tenant row
    # there wouldn't show up in the substring checks above — it would only
    # inflate a number. test_family has none of its own rows in any of
    # these tables, so every one of these must be an empty/zero baseline;
    # a nonzero value here means the "other" family's row was counted.
    assert body["tasks"]["by_status"] == {}
    assert body["budget"]["account_count"] == 0
    assert body["budget"]["transaction_count"] == 0
    assert body["budget"]["receipt_drafts_pending"] == 0
    assert body["integrations"]["deliveries_by_status"] == {}


@pytest.mark.asyncio
async def test_family_detail_rejects_parent_of_that_family(
    client, auth_headers, test_family, allowlist_superadmin
):
    """A parent cannot read their OWN family through the admin surface."""
    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_every_action_route_404s_for_non_operator(
    client, auth_headers, test_family, test_parent_user, allowlist_superadmin
):
    """A parent must not reach ANY operator action, on their own family or
    anyone else's."""
    fid, uid = test_family.id, test_parent_user.id
    calls = [
        (f"/api/admin/families/{fid}/comp-plus", {"reason": "x", "days": 30}),
        (f"/api/admin/families/{fid}/suspend", {"reason": "x", "suspended": True}),
        (f"/api/admin/families/{fid}/modules", {"reason": "x"}),
        (f"/api/admin/users/{uid}/active", {"reason": "x", "active": False}),
        (f"/api/admin/users/{uid}/resend-verification", {"reason": "x"}),
        (f"/api/admin/users/{uid}/password-reset", {"reason": "x"}),
        # Task 10 actions — added here (not in the task-10 brief, which did
        # not touch this file) because this is the one test guarding the
        # "admin routes 404, never 403, for a non-operator" constraint that
        # Task 10's own brief restates; without this addition a future
        # operator route could forget Depends(require_superadmin) and leak
        # via 403 with nothing here to catch it.
        (f"/api/admin/families/{fid}/cancel-deletion", {"reason": "x"}),
        (
            f"/api/admin/families/{fid}/release-paycheck",
            {"reason": "x", "kid_id": str(uid), "week_of": "2026-07-20"},
        ),
        (f"/api/admin/families/{fid}/assignments/{uid}/undo-approval", {"reason": "x"}),
        (
            f"/api/admin/families/{fid}/restore",
            {"reason": "x", "item_type": "transaction", "item_id": str(uid)},
        ),
    ]
    for path, body in calls:
        resp = await client.post(path, json=body, headers=auth_headers)
        assert resp.status_code == 404, path
