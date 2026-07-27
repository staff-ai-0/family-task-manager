"""Operator actions and their audit trail."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.operator_audit import OperatorAuditLog
from app.services.admin.operator_audit_service import OperatorAuditService


@pytest.mark.asyncio
async def test_audit_record_stages_without_committing(
    db_session, test_superadmin_user, test_family
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="family.suspend",
        target_family_id=test_family.id,
        params={"reason": "abuse"},
    )
    # Not committed yet — a rollback must erase it entirely.
    await db_session.rollback()
    rows = (await db_session.execute(select(OperatorAuditLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_audit_record_persists_on_commit(
    db_session, test_superadmin_user, test_family
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="family.suspend",
        target_family_id=test_family.id,
        params={"reason": "abuse"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(OperatorAuditLog))).scalar_one()
    assert row.action == "family.suspend"
    assert row.actor_email == "superadmin@test.com"
    assert row.actor_user_id == test_superadmin_user.id
    assert row.target_family_id == test_family.id
    assert row.result == "ok"
    assert row.params == {"reason": "abuse"}


@pytest.mark.asyncio
async def test_audit_record_redacts_secret_params(
    db_session, test_superadmin_user
):
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="user.password_reset",
        params={"password": "hunter2", "token": "abc", "email": "a@b.com"},
    )
    await db_session.commit()
    row = (await db_session.execute(select(OperatorAuditLog))).scalar_one()
    assert row.params["password"] == "***"
    assert row.params["token"] == "***"
    assert row.params["email"] == "a@b.com"


@pytest.mark.asyncio
async def test_comp_plus_month_extends_referral_bonus_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "goodwill"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert test_family.referral_bonus_until is not None

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.comp_plus"
            )
        )
    ).scalar_one()
    assert row.target_family_id == test_family.id
    assert row.params["days"] == 30
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_comp_plus_month_sets_absolute_expiry_not_stacked(
    client, db_session, superadmin_headers, test_family
):
    """Two comps of 30 days must not silently become 60.

    ReferralService._grant_referral_month stacks +30d per call; the operator
    action deliberately does NOT use it and writes an absolute expiry.
    """
    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "one"},
        headers=superadmin_headers,
    )
    await db_session.refresh(test_family)
    first = test_family.referral_bonus_until

    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "two"},
        headers=superadmin_headers,
    )
    await db_session.refresh(test_family)
    delta = abs((test_family.referral_bonus_until - first).total_seconds())
    assert delta < 5


@pytest.mark.asyncio
async def test_suspend_family_sets_is_active_false_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/suspend",
        json={"suspended": True, "reason": "abuse report"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert test_family.is_active is False

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.suspend"
            )
        )
    ).scalar_one()
    assert row.params["reason"] == "abuse report"


@pytest.mark.asyncio
async def test_set_modules_persists_registry_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/modules",
        json={"enabled_modules": ["budget", "chat"], "reason": "support"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_family)
    assert set(test_family.enabled_modules) == {"budget", "chat"}

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.set_modules"
            )
        )
    ).scalar_one()
    assert row.target_family_id == test_family.id
    assert row.result == "ok"
    assert set(row.params["enabled_modules"]) == {"budget", "chat"}


@pytest.mark.asyncio
async def test_set_modules_rejects_unknown_module_key(
    client, db_session, superadmin_headers, test_family
):
    """The rejection path (unknown keys against TOGGLABLE_MODULES) had zero
    coverage — this pins the 422 and confirms nothing was written.

    ``reason`` must satisfy ReasonRequest's own min_length=3 — a too-short
    reason (e.g. "x") also 422s, but from Pydantic body validation before
    the route ever runs, which would make this test pass even if the
    TOGGLABLE_MODULES check were deleted. Asserting the detail string pins
    it to the actual rejection path in admin_action_service.set_modules.
    """
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/modules",
        json={
            "enabled_modules": ["budget", "not_a_real_module"],
            "reason": "support",
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 422
    assert "unknown modules" in resp.json()["detail"]

    await db_session.refresh(test_family)
    assert test_family.enabled_modules is None

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.set_modules"
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_password_reset_bumps_token_version(
    client, db_session, superadmin_headers, test_parent_user, monkeypatch
):
    """The EmailService helper does NOT bump token_version — the public route
    does. An operator reset that skipped it would leave sessions alive."""
    from app.services.email_service import EmailService

    async def _fake_send(db, user, base_url=""):
        return True

    monkeypatch.setattr(
        EmailService, "send_password_reset_email", staticmethod(_fake_send)
    )
    before = test_parent_user.token_version

    resp = await client.post(
        f"/api/admin/users/{test_parent_user.id}/password-reset",
        json={"reason": "user locked out"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(test_parent_user)
    assert test_parent_user.token_version == before + 1


@pytest.mark.asyncio
async def test_failed_action_writes_error_audit_row(
    client, db_session, superadmin_headers, test_parent_user, monkeypatch
):
    from app.services.email_service import EmailService

    async def _boom(db, user, base_url=""):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(
        EmailService, "send_verification_email", staticmethod(_boom)
    )
    resp = await client.post(
        f"/api/admin/users/{test_parent_user.id}/resend-verification",
        json={"reason": "never arrived"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 502

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "user.resend_verification"
            )
        )
    ).scalar_one()
    assert row.result == "error"
    assert "smtp down" in row.error


@pytest.mark.asyncio
async def test_deactivate_user_audits_and_flags_asymmetry(
    client, db_session, superadmin_headers, test_child_user, test_family
):
    resp = await client.post(
        f"/api/admin/users/{test_child_user.id}/active",
        json={"active": False, "reason": "parent request"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["warning"]
    await db_session.refresh(test_child_user)
    assert test_child_user.is_active is False

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "user.deactivate"
            )
        )
    ).scalar_one()
    assert row.target_family_id == test_family.id
    assert row.target_user_id == test_child_user.id
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_deactivate_user_is_atomic_with_its_audit_row(
    client, db_session, superadmin_headers, test_child_user, monkeypatch
):
    """Proves the Task 9 fix, not just an already-correct path.

    A prior version called AuthService.deactivate_user with its OWN internal
    commit, so the member mutation (and its bulk assignment-cancellation)
    landed in a transaction separate from — and earlier than — the audit
    row. If staging/committing the audit row then failed, the member stayed
    permanently deactivated with zero audit trail.

    This forces exactly that failure window: OperatorAuditService.record is
    made to raise on its first call, which happens AFTER
    AuthService.deactivate_user(..., commit=False) has mutated the user
    in-session but BEFORE the single shared commit. A row-exists assertion
    cannot distinguish the fixed (atomic) behaviour from the old (split)
    one; only checking that the mutation ALSO rolled back can. The second
    call to record() (the error-path logging in the except block) is let
    through so the failure is still auditable.
    """
    from app.services.admin.operator_audit_service import (
        OperatorAuditService as OAS,
    )

    real_record = OAS.record
    call_count = {"n": 0}

    def _raise_once_then_record(db, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("audit staging exploded")
        return real_record(db, **kwargs)

    monkeypatch.setattr(OAS, "record", staticmethod(_raise_once_then_record))

    resp = await client.post(
        f"/api/admin/users/{test_child_user.id}/active",
        json={"active": False, "reason": "force failure"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 500

    # The mutation must NOT have survived — this is the assertion that
    # actually proves atomicity. Verified empirically (not just by
    # construction) against the actual pre-fix code at commit 097d088: run
    # there, this test doesn't even reach this assertion. Pre-fix,
    # AuthService.deactivate_user committed internally and
    # AdminActionService had no try/except around OperatorAuditService.record
    # at all, so the injected RuntimeError propagates unhandled straight
    # through the route, FastAPI/Starlette's middleware stack, and out
    # through httpx — the test FAILS at the `client.post(...)` call above
    # with a raw `RuntimeError: audit staging exploded`, never reaching a
    # response object at all. Post-fix, the same failure is caught, the
    # transaction (mutation + attempted "ok" row) is rolled back, a
    # result="error" row is committed on its own, and the route returns a
    # clean 500 — which is what makes it meaningful to assert on
    # `is_active` and the audit row below at all.
    await db_session.refresh(test_child_user)
    assert test_child_user.is_active is True

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "user.deactivate"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].result == "error"
    assert "audit staging exploded" in rows[0].error


@pytest.mark.asyncio
async def test_error_audit_row_written_even_when_refresh_would_fail(
    client, db_session, superadmin_headers, test_family, monkeypatch
):
    """Proves the round-2 Critical fix: the error-audit path must not
    depend on being able to re-query ANY ORM object (in particular, the
    operator) after the db.rollback() the failure handler issues.

    A prior version called ``await db.refresh(operator)`` in exactly this
    window, to work around rollback() expiring the operator object loaded
    earlier by require_superadmin. That refresh is itself a real, unguarded
    round of IO — on a dead connection or a concurrently-deleted operator
    row it raises, and since it ran BEFORE OperatorAuditService.record and
    the recovery commit, its failure meant record() was never reached and
    the mutating action failed with ZERO audit trail: precisely the
    "silent failure" outcome the whole error-path-audit requirement exists
    to prevent, for the exact class of failure (an IO error under load)
    where the trail matters most.

    The fix removed the refresh entirely (capturing operator.id/.email into
    locals before the try, and passing a detached stand-in to record()
    instead). This test proves that removal rather than merely trusting the
    diff: it patches AsyncSession.refresh to explode on ANY call, forces
    the same "exception between mutation and commit" window as the
    atomicity test above, and asserts the audit row is STILL written
    correctly and the client still gets the intended message. If a
    regression reintroduced `db.refresh(operator)` on this path, the patched
    refresh would raise inside `_record_failure`'s own recovery try/except —
    which swallows it (by design, see `_record_failure`'s docstring) — so
    the regression would surface here as a MISSING audit row, not as the
    injected exception bubbling up; the assertions below cover exactly
    that.
    """
    from sqlalchemy.ext.asyncio import AsyncSession as AsyncSessionCls

    async def _refresh_must_not_be_called(self, *args, **kwargs):
        raise RuntimeError(
            "AsyncSession.refresh must not be called on the admin-action "
            "error-audit path — this is the defect the fix removed"
        )

    monkeypatch.setattr(AsyncSessionCls, "refresh", _refresh_must_not_be_called)

    real_record = OperatorAuditService.record
    call_count = {"n": 0}

    def _raise_once_then_record(db, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("comp plus exploded")
        return real_record(db, **kwargs)

    monkeypatch.setattr(
        OperatorAuditService, "record", staticmethod(_raise_once_then_record)
    )

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "force failure"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 500
    assert "comp plus failed" in resp.json()["detail"]

    # Restore the real refresh()/record() before using db_session ourselves
    # to verify final state below.
    monkeypatch.undo()

    await db_session.refresh(test_family)
    assert test_family.referral_bonus_until is None

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.comp_plus"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].result == "error"
    assert "comp plus exploded" in rows[0].error
    assert rows[0].actor_email == "superadmin@test.com"


@pytest.mark.asyncio
async def test_cancel_deletion_clears_tombstones_and_audits(
    client, db_session, superadmin_headers, test_family, test_parent_user
):
    now = datetime.now(timezone.utc)
    test_family.deleted_at = now
    test_parent_user.deleted_at = now
    await db_session.commit()

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "closed by mistake"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["billing_restored"] is False

    await db_session.refresh(test_family)
    await db_session.refresh(test_parent_user)
    assert test_family.deleted_at is None
    assert test_parent_user.deleted_at is None

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.cancel_deletion"
            )
        )
    ).scalar_one()
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_cancel_deletion_refuses_past_retention_window(
    client, db_session, superadmin_headers, test_family
):
    test_family.deleted_at = datetime.now(timezone.utc) - timedelta(days=45)
    await db_session.commit()

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "too late"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_deletion_on_live_family_is_a_noop_409(
    client, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/cancel-deletion",
        json={"reason": "nothing to undo"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_undo_chore_approval_rejects_bonus_assignment(
    client, db_session, superadmin_headers, test_family, test_child_user,
    gig_template_factory,
):
    """patch_assignment refuses bonus/gig reversals. The operator route must
    surface that refusal rather than fail opaquely.

    Deviation from the task-10 brief (see task-10-report.md): the brief's
    version of this test omitted ``family=test_family`` on the factory call
    (a required kwarg — TypeError), omitted
    ``approval_status=ApprovalStatus.APPROVED`` on the assignment (without
    it, TaskAssignmentService.patch_assignment does not refuse the reversal
    at all — verified empirically against the real logic at
    backend/app/services/task_assignment_service.py:2254, which only refuses
    a bonus/gig reversal when approval_status is APPROVED, "already approved
    and paid out"), and omitted ``assigned_date``/``week_of``
    (task_assignments has NOT NULL constraints on both, neither has a
    default). All four are fixed here so the test actually exercises the
    refusal path it documents.
    """
    from app.models.task_assignment import (
        ApprovalStatus,
        AssignmentStatus,
        TaskAssignment,
    )

    today = date.today()
    template = await gig_template_factory(family=test_family)
    assignment = TaskAssignment(
        template_id=template.id,
        family_id=test_family.id,
        assigned_to=test_child_user.id,
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.APPROVED,
        assigned_date=today,
        week_of=today - timedelta(days=today.weekday()),
    )
    db_session.add(assignment)
    await db_session.commit()
    await db_session.refresh(assignment)

    resp = await client.post(
        f"/api/admin/families/{test_family.id}/assignments/{assignment.id}/undo-approval",
        json={"reason": "approved by mistake"},
        headers=superadmin_headers,
    )
    assert resp.status_code in (400, 422)
    # A bare 4xx would also pass if undo_chore_approval swallowed
    # patch_assignment's refusal and returned some other 4xx (e.g. a
    # generic validation error) — assert the operator actually sees
    # patch_assignment's own refusal message, verbatim, not an opaque one.
    assert "already approved and paid out" in resp.json()["message"]
    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "assignment.undo_approval"
            )
        )
    ).scalar_one()
    assert row.result == "error"
    assert "already approved and paid out" in row.error


@pytest.mark.asyncio
async def test_release_paycheck_through_route_credits_audits_and_is_idempotent(
    client, db_session, superadmin_headers, test_family, test_child_user,
    mandatory_template_factory,
):
    """Exercises release_paycheck through the actual admin route (previously
    untested at this layer — the money path). A double-release must 409 on
    the second attempt, write an error audit row, and NOT credit twice.

    ``family_id``/``kid_id`` are captured as locals up front, and every
    later reference uses them instead of re-reading ``test_family.id``/
    ``test_child_user.id`` — the second (409) call's error path calls
    ``_record_failure``, which rolls back and expires every object on this
    shared session (same rule this task's production fix applies): reading
    an ORM attribute off `test_family`/`test_child_user` after that without
    an explicit ``await ... .refresh()`` raises ``MissingGreenlet``, which is
    exactly what an earlier draft of this test did.
    """
    from app.models.cash_transaction import CashTransaction, CashTransactionType
    from app.models.task_assignment import AssignmentStatus, TaskAssignment
    from app.services.bank_service import BankService

    family_id = test_family.id
    kid_id = test_child_user.id
    today = date.today()
    week_monday = today - timedelta(days=today.weekday())

    # Chore-proportional allowance, funded and fully earned this week so the
    # release actually moves money (not just a $0 ledger row).
    acct = await BankService.ensure_account(db_session, test_child_user)
    acct.allowance_mode = "chore_proportional"
    acct.allowance_cents = 10000
    await db_session.commit()

    template = await mandatory_template_factory(family=test_family, points=10)
    assignment = TaskAssignment(
        template_id=template.id,
        family_id=family_id,
        assigned_to=kid_id,
        status=AssignmentStatus.COMPLETED,
        assigned_date=today,
        week_of=week_monday,
    )
    db_session.add(assignment)
    await db_session.commit()

    resp = await client.post(
        f"/api/admin/families/{family_id}/release-paycheck",
        json={
            "kid_id": str(kid_id),
            "week_of": week_monday.isoformat(),
            "reason": "kid never got Sunday's paycheck",
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["amount_cents"] == 10000

    ok_row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "bank.release_paycheck",
                OperatorAuditLog.result == "ok",
            )
        )
    ).scalar_one()
    assert ok_row.target_user_id == kid_id
    assert ok_row.params["week_of"] == week_monday.isoformat()

    ledger_rows = (
        await db_session.execute(
            select(CashTransaction).where(
                CashTransaction.user_id == kid_id,
                CashTransaction.type == CashTransactionType.ALLOWANCE,
                CashTransaction.week_of == week_monday,
            )
        )
    ).scalars().all()
    assert len(ledger_rows) == 1
    await db_session.refresh(test_child_user)
    cash_after_first = test_child_user.cash_cents
    assert cash_after_first == 10000

    # Second release for the same (kid, week) — BankService's own idempotency
    # check must 409, and that failure must be audited too.
    resp2 = await client.post(
        f"/api/admin/families/{family_id}/release-paycheck",
        json={
            "kid_id": str(kid_id),
            "week_of": week_monday.isoformat(),
            "reason": "double-checking",
        },
        headers=superadmin_headers,
    )
    assert resp2.status_code == 409

    error_row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "bank.release_paycheck",
                OperatorAuditLog.result == "error",
            )
        )
    ).scalar_one()
    assert "already released" in error_row.error

    # No second credit: same single ledger row, same cash balance.
    ledger_rows_after = (
        await db_session.execute(
            select(CashTransaction).where(
                CashTransaction.user_id == kid_id,
                CashTransaction.type == CashTransactionType.ALLOWANCE,
                CashTransaction.week_of == week_monday,
            )
        )
    ).scalars().all()
    assert len(ledger_rows_after) == 1
    await db_session.refresh(test_child_user)
    assert test_child_user.cash_cents == cash_after_first


@pytest.mark.asyncio
async def test_restore_recycled_through_route_audits_ok_and_error_paths(
    client, db_session, superadmin_headers, test_family,
):
    """Exercises restore_recycled through the actual admin route (previously
    untested at this layer): a happy-path restore, an unknown item_type
    (422, never reaches a restorer), and a downstream NotFoundException from
    the restorer itself (item already restored / wrong id) — all three must
    be audited.

    ``family_id``/``item_id`` are captured as locals up front and reused for
    every request — see the release_paycheck test above for why: the 422 and
    404 requests each trigger ``_record_failure``'s rollback, which expires
    `test_family` (and `txn`) on this shared session, so re-reading
    `test_family.id`/`txn.id` afterward raises ``MissingGreenlet``.
    """
    from app.models.budget import BudgetAccount, BudgetTransaction

    family_id = test_family.id
    account = BudgetAccount(
        family_id=family_id, name="Cash", type="checking", currency="MXN"
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    txn = BudgetTransaction(
        family_id=family_id, account_id=account.id, date=date.today(),
        amount=-500,
    )
    db_session.add(txn)
    await db_session.commit()
    await db_session.refresh(txn)
    item_id = txn.id
    txn.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Happy path.
    resp = await client.post(
        f"/api/admin/families/{family_id}/restore",
        json={
            "reason": "parent asked us to bring it back",
            "item_type": "transaction",
            "item_id": str(item_id),
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"restored": True, "item_type": "transaction"}

    ok_row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "budget.restore",
                OperatorAuditLog.result == "ok",
            )
        )
    ).scalar_one()
    assert ok_row.params["item_id"] == str(item_id)

    # Unknown item_type — 422, never reaches a restorer, still audited.
    resp = await client.post(
        f"/api/admin/families/{family_id}/restore",
        json={
            "reason": "typo test",
            "item_type": "not_a_real_type",
            "item_id": str(item_id),
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 422

    # Same item again — it's already live (deleted_at is now NULL), so the
    # restorer itself raises NotFoundException. Also the realistic
    # "operator targets an item that's already live" failure mode.
    resp = await client.post(
        f"/api/admin/families/{family_id}/restore",
        json={
            "reason": "already restored",
            "item_type": "transaction",
            "item_id": str(item_id),
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 404

    error_rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "budget.restore",
                OperatorAuditLog.result == "error",
            )
        )
    ).scalars().all()
    assert len(error_rows) == 2
    assert any("unknown item_type" in (r.error or "") for r in error_rows)
    assert any("not found" in (r.error or "").lower() for r in error_rows)
