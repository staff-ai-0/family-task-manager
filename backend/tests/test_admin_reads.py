"""Admin read surfaces and the instrumentation they depend on."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Update, select
from sqlalchemy.engine.base import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_last_seen_at_stamped_on_authenticated_request(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at is not None


@pytest.mark.asyncio
async def test_last_seen_at_not_rewritten_within_throttle_window(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    first = test_parent_user.last_seen_at

    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at == first


@pytest.mark.asyncio
async def test_last_seen_at_rewritten_once_throttle_elapses(
    client, db_session, auth_headers, test_parent_user
):
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    test_parent_user.last_seen_at = stale
    await db_session.commit()

    await client.get("/api/auth/me", headers=auth_headers)
    refreshed = (
        await db_session.execute(
            select(User).where(User.id == test_parent_user.id)
        )
    ).scalar_one()
    assert refreshed.last_seen_at > stale


@pytest.mark.asyncio
async def test_last_seen_write_failure_does_not_break_request(
    client, db_session, auth_headers, test_parent_user, monkeypatch
):
    """The activity stamp is best-effort: if the write inside
    _touch_last_seen fails, the request must still succeed AND the user
    object must still be usable by downstream code (route handlers read
    attributes synchronously — e.g. UserResponse.model_validate(current_user)
    in GET /api/auth/me) — with no further unguarded database IO on the
    failure path.

    Poisons both the UPDATE on `users` (the primary write attempt) AND
    AsyncSession.refresh on this same user instance (the residual recovery
    call a rollback-then-refresh fix would issue). AsyncSession.refresh is
    implemented via greenlet_spawn(sync_session.refresh, ...) — it does not
    go through AsyncSession.execute — so a fix that depends on refresh()
    succeeding after a failed write is not exercised by patching execute()
    alone; this simulates a dead-connection-style failure where that
    recovery read would also fail. The correct fix (a SAVEPOINT whose
    rollback never expires `user` in the first place) needs no recovery
    read at all and never calls refresh(), so it is unaffected.
    """
    original_execute = AsyncSession.execute
    original_refresh = AsyncSession.refresh

    async def failing_execute(self, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "users":
            raise RuntimeError("simulated last_seen_at write failure")
        return await original_execute(self, statement, *args, **kwargs)

    async def failing_refresh(self, instance, *args, **kwargs):
        if instance is test_parent_user:
            raise RuntimeError("simulated dead-connection refresh failure")
        return await original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)
    monkeypatch.setattr(AsyncSession, "refresh", failing_refresh)

    response = await client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["email"] == test_parent_user.email


@pytest.mark.asyncio
async def test_last_seen_commit_failure_leaves_session_committable(
    client, db_session, auth_headers, test_parent_user, monkeypatch
):
    """A transient failure in _touch_last_seen's own outer db.commit() (a
    connection-level DBAPI failure, not a full DB outage) must not leave
    the session's transaction wedged in a PREPARED state: PREPARED blocks
    ANY further SQL on that session — including get_db()'s own
    end-of-request `await session.commit()` — which would 500 the request
    for reasons unrelated to `last_seen_at` no matter which route was hit.

    Patching AsyncSession.commit (as an earlier round's test did) is too
    shallow: it bypasses SessionTransaction._prepare_impl(), which is what
    flips the transaction to PREPARED before the real per-connection
    commit runs. This test instead fault-injects at
    Connection._commit_impl — the actual DBAPI commit boundary — so the
    state transition that causes the wedge is genuinely exercised.

    Both invariants must hold: (a) the response is 200 with the expected
    body (user stayed usable for route/response-model attribute reads),
    and (b) the shared session can still run a further query and commit
    afterward — the direct equivalent of get_db()'s own post-yield commit
    succeeding rather than raising PendingRollbackError/InvalidRequestError.
    """
    original_commit_impl = Connection._commit_impl
    fail_once = {"armed": True}

    def poisoned_commit_impl(self):
        if fail_once["armed"]:
            fail_once["armed"] = False
            raise RuntimeError("simulated transient DBAPI commit failure")
        return original_commit_impl(self)

    monkeypatch.setattr(Connection, "_commit_impl", poisoned_commit_impl)

    response = await client.get("/api/auth/me", headers=auth_headers)

    # Invariant (a).
    assert response.status_code == 200
    assert response.json()["email"] == test_parent_user.email

    # Invariant (b): the session must still accept further SQL and commit —
    # exactly what get_db() does at the end of every real request on this
    # same session. A PREPARED-wedged session raises here instead.
    result = await db_session.execute(
        select(User).where(User.id == test_parent_user.id)
    )
    assert result.scalar_one().email == test_parent_user.email
    await db_session.commit()

    # Belt-and-suspenders: the session should also be fully usable for a
    # subsequent, unrelated request (not just a bare query/commit).
    response2 = await client.get("/api/auth/me", headers=auth_headers)
    assert response2.status_code == 200


@pytest.mark.asyncio
async def test_last_seen_at_naive_stored_value_does_not_break_request(
    client, db_session, auth_headers, test_parent_user
):
    """A naive (tzinfo-less) last_seen_at should never reach the column via
    SQLAlchemy, but if one ever did (e.g. a raw-SQL backfill/import script),
    comparing it against an aware `now` must not raise an unhandled
    TypeError — the stamp is best-effort and must degrade gracefully."""
    test_parent_user.last_seen_at = datetime(2020, 1, 1)  # naive
    await db_session.commit()

    response = await client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["email"] == test_parent_user.email


@pytest.mark.asyncio
async def test_platform_pulse_counts_exclude_soft_deleted(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    from app.models.family import Family

    gone = Family(name="Closed Family", deleted_at=datetime.now(timezone.utc))
    db_session.add(gone)
    await db_session.commit()

    resp = await client.get("/api/admin/overview", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["families_total"] == 1
    assert body["families_pending_purge"] == 1
    assert body["users_total"] >= 1


@pytest.mark.asyncio
async def test_platform_pulse_rejects_non_operator(client, auth_headers):
    resp = await client.get("/api/admin/overview", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_platform_pulse_excludes_closed_family_except_billing_review(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    """A closed (soft-deleted) family's rows must not pollute the
    actionable queues or MRR — but an unresolved billing dispute on that
    same family must still surface (a closed account doesn't settle a
    chargeback).

    Regression test for the fact that FamilyDeletionService.delete_family
    (backend/app/services/family_deletion_service.py) stamps
    Family.deleted_at / User.deleted_at at soft-delete time but does NOT
    touch FamilySubscription.status, BudgetReceiptDraft, TaskAssignment, or
    A2AWebhookDelivery rows — those are only cleaned up (or, for the
    subscription, flipped to 'cancelled') by out-of-band sweeps, up to the
    full 30-day purge retention window later. So a closed family can have a
    live-looking 'active' subscription with a real paypal_subscription_id,
    and pending/overdue rows in every queue, for weeks after closing.
    """
    from app.core.security import get_password_hash
    from app.models.a2a import A2AWebhookDelivery
    from app.models.budget import BudgetAccount, BudgetReceiptDraft, BudgetTransaction
    from app.models.family import Family
    from app.models.subscription import FamilySubscription, SubscriptionPlan
    from app.models.task_assignment import AssignmentStatus, TaskAssignment
    from app.models.task_template import TaskTemplate
    from app.models.user import User, UserRole

    gone = Family(name="Closed Family", deleted_at=datetime.now(timezone.utc))
    db_session.add(gone)
    await db_session.flush()

    member = User(
        email="closed-member@test.com",
        password_hash=get_password_hash("password123"),
        name="Closed Member",
        role=UserRole.CHILD,
        family_id=gone.id,
        email_verified=True,
        points=0,
    )
    db_session.add(member)
    await db_session.flush()

    plan = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        currency="USD", price_monthly_cents=500, price_annual_cents=5000,
    )
    db_session.add(plan)
    await db_session.flush()

    db_session.add(
        FamilySubscription(
            family_id=gone.id, plan_id=plan.id, billing_cycle="monthly",
            status="active", paypal_subscription_id="I-CLOSED-SUB",
            needs_review=True,
        )
    )
    db_session.add(
        BudgetReceiptDraft(
            family_id=gone.id, scanned_data={"total_amount": 10.0},
            confidence=0.1, status="pending",
        )
    )

    template = TaskTemplate(title="Closed chore", family_id=gone.id)
    db_session.add(template)
    await db_session.flush()

    today = datetime.now(timezone.utc).date()
    db_session.add(
        TaskAssignment(
            template_id=template.id, assigned_to=member.id, family_id=gone.id,
            status=AssignmentStatus.OVERDUE,
            assigned_date=today, week_of=today,
        )
    )

    account = BudgetAccount(
        family_id=gone.id, name="Closed Cash", type="checking", currency="MXN",
    )
    db_session.add(account)
    await db_session.flush()

    txn = BudgetTransaction(
        family_id=gone.id, account_id=account.id, date=today, amount=-100,
    )
    db_session.add(txn)
    await db_session.flush()

    db_session.add(
        A2AWebhookDelivery(
            family_id=gone.id, transaction_id=txn.id,
            payload_json={"a": 1}, status="pending", attempts=0,
        )
    )

    await db_session.commit()

    resp = await client.get("/api/admin/overview", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()

    # Actionable queues + revenue: the closed family's rows must not appear.
    assert body["receipt_drafts_pending"] == 0
    assert body["overdue_assignments"] == 0
    assert body["mrr"] == []
    assert body["a2a"]["by_status"].get("pending", 0) == 0
    assert body["a2a"]["oldest_pending_at"] is None

    # Deliberate exception: an unresolved billing dispute still counts even
    # though the family that filed it has since closed its account.
    assert body["billing_needs_review"] == 1


@pytest.mark.asyncio
async def test_platform_pulse_mrr_excludes_comped_counts_only_paypal_backed(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    """The entitlement-vs-revenue predicate is the trickiest clause in the
    spec: three paths grant Plus with no money changing hands (a referral
    bonus, the payment-failure grace window, and the free-limits fallback).
    Only a subscription row with a live paypal_subscription_id counts as
    revenue. Seeds one comped family (no paypal_subscription_id — the
    referral-bonus/comp case) and one genuinely paying family on the same
    plan/currency, and asserts the comped family contributes zero to MRR
    while the paying family contributes exactly its plan price.
    """
    from app.models.family import Family
    from app.models.subscription import FamilySubscription, SubscriptionPlan

    plan = SubscriptionPlan(
        name="plus", display_name="Plus", display_name_es="Plus",
        currency="MXN", price_monthly_cents=15000, price_annual_cents=150000,
    )
    db_session.add(plan)
    await db_session.flush()

    comped_family = Family(name="Comped Family")
    paying_family = Family(name="Paying Family")
    db_session.add_all([comped_family, paying_family])
    await db_session.flush()

    db_session.add(
        FamilySubscription(
            family_id=comped_family.id, plan_id=plan.id, billing_cycle="monthly",
            status="active", paypal_subscription_id=None,
        )
    )
    db_session.add(
        FamilySubscription(
            family_id=paying_family.id, plan_id=plan.id, billing_cycle="monthly",
            status="active", paypal_subscription_id="I-REAL-PAYER",
        )
    )
    await db_session.commit()

    resp = await client.get("/api/admin/overview", headers=superadmin_headers)
    assert resp.status_code == 200
    body = resp.json()

    mxn_bucket = next(b for b in body["mrr"] if b["currency"] == "MXN")
    assert mxn_bucket["subscriptions"] == 1
    assert mxn_bucket["cents"] == 15000
