"""Operator actions and their audit trail."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.operator_audit import OperatorAuditLog
from app.services.admin.operator_audit_service import OperatorAuditService
from conftest import current_week_monday, family_local_today


async def _active_credit_end(db, family_id):
    """End of the family's latest credit window, or None.

    Replaces the old single-timestamp `families` credit-expiry column
    assertion — same behavior, now stored as a PlanCreditGrant row.

    Deliberately NOT scoped to PlanCreditService.active_grants (which filters
    to starts_at <= now): a credit stacked behind another grant is QUEUED
    rather than active yet — exactly the state the old raw timestamp column
    represented just as well as an already-running credit (never conditioned
    on "has this actually started"). This mirrors
    PlanCreditService.next_window_start's own anchor query, which looks at
    every non-revoked, dated grant regardless of whether it has started (see
    test_comp_plus_now_stacks_like_any_other_grant, which needs the SECOND,
    still-queued grant's end).
    """
    from sqlalchemy import select as _select

    from app.models.plan_credit import PlanCreditGrant

    return (
        await db.execute(
            _select(PlanCreditGrant.ends_at)
            .where(
                PlanCreditGrant.family_id == family_id,
                PlanCreditGrant.revoked_at.is_(None),
                PlanCreditGrant.ends_at.is_not(None),
            )
            .order_by(PlanCreditGrant.ends_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


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
async def test_audit_record_truncates_long_error_strings(
    db_session, test_superadmin_user
):
    """A DBAPIError's str() can embed the SQL statement AND its bound
    parameters — for create_verification_token / create_password_reset_
    token that means a freshly-minted token. The audit log is append-only
    and rendered verbatim on /admin/audit, so `error` is capped, same as
    `params` is redacted, rather than persisted unbounded."""
    from app.services.admin.operator_audit_service import _ERROR_MAX_LEN

    long_error = "x" * (_ERROR_MAX_LEN + 200)
    OperatorAuditService.record(
        db_session,
        actor=test_superadmin_user,
        action="user.password_reset",
        result="error",
        error=long_error,
    )
    await db_session.commit()
    row = (await db_session.execute(select(OperatorAuditLog))).scalar_one()
    assert len(row.error) == _ERROR_MAX_LEN
    assert row.error == long_error[:_ERROR_MAX_LEN]


@pytest.mark.asyncio
async def test_comp_plus_grants_plan_credit_and_audits(
    client, db_session, superadmin_headers, test_family
):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "goodwill"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "plus"
    assert await _active_credit_end(db_session, test_family.id) is not None

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.grant_credit"
            )
        )
    ).scalar_one()
    assert row.target_family_id == test_family.id
    assert row.params["days"] == 30
    assert row.params["tier"] == "plus"
    assert row.result == "ok"


@pytest.mark.asyncio
async def test_comp_plus_now_stacks_like_any_other_grant(
    client, db_session, superadmin_headers, test_family
):
    """Two comps of 30 days now total ~60, not 30.

    comp_plus_month used to write an ABSOLUTE expiry specifically so repeated
    comps did not stack — a guarantee unique to that one write path. It is
    gone: /comp-plus is now a thin alias over the general grant_plan_credit,
    which goes through PlanCreditService.grant like every other credit
    source (coupon, referral, operator), and grants stack additively by
    design — see test_plan_credit_service.test_grants_stack_additively, the
    behavior this task's amendment explicitly keeps. An operator who wants
    to RESET a family's comp instead of extending it now has a real tool for
    that intent (revoke the old grant, then issue a fresh one) rather than
    relying on this route's old, comp-only idempotent-overwrite behavior.
    """
    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "one"},
        headers=superadmin_headers,
    )
    first_end = await _active_credit_end(db_session, test_family.id)
    assert first_end is not None

    await client.post(
        f"/api/admin/families/{test_family.id}/comp-plus",
        json={"days": 30, "reason": "two"},
        headers=superadmin_headers,
    )
    second_end = await _active_credit_end(db_session, test_family.id)

    delta_days = (second_end - first_end).total_seconds() / 86400
    assert 29 <= delta_days <= 31


@pytest.mark.asyncio
async def test_suspend_family_sets_is_active_false_and_audits(
    client, db_session, superadmin_headers, other_family
):
    """Targets other_family, NOT test_family: test_superadmin_user belongs
    to test_family, and suspending the operator's own family is refused
    (see test_cannot_suspend_own_family_or_deactivate_own_account below)."""
    resp = await client.post(
        f"/api/admin/families/{other_family.id}/suspend",
        json={"suspended": True, "reason": "abuse report"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    await db_session.refresh(other_family)
    assert other_family.is_active is False

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.suspend"
            )
        )
    ).scalar_one()
    assert row.params["reason"] == "abuse report"


@pytest.mark.asyncio
async def test_cannot_suspend_own_family(
    client, db_session, superadmin_headers, test_family, test_superadmin_user
):
    """test_superadmin_user belongs to test_family. Suspending it would lock
    the operator out with no in-app recovery — the frontend guard 404s
    /admin and password login refuses; recovery would need psql on the prod
    host. Must refuse with 422, not silently no-op or 500."""
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/suspend",
        json={"suspended": True, "reason": "oops, wrong row"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422
    await db_session.refresh(test_family)
    assert test_family.is_active is True

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.suspend"
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_can_still_reinstate_own_family(
    db_session, test_family, test_superadmin_user
):
    """The refusal only blocks the SUSPEND direction — reinstating (which
    can only ever help, never lock anyone out) must still work.

    Exercised at the SERVICE layer, not through the HTTP client: suspending
    test_family also suspends test_superadmin_user's own session (family.
    is_active gates every request in get_current_user), so a client.post
    with that operator's own token would 401 "Family suspended" before ever
    reaching the route — an artifact of self-locking the test's own actor,
    not of the guard being tested here.
    """
    from app.services.admin.admin_action_service import AdminActionService

    test_family.is_active = False
    await db_session.commit()

    result = await AdminActionService.set_family_active(
        db_session,
        operator=test_superadmin_user,
        family_id=test_family.id,
        suspended=False,
        reason="reinstating",
    )
    assert result == {"is_active": True}
    await db_session.refresh(test_family)
    assert test_family.is_active is True


@pytest.mark.asyncio
async def test_cannot_deactivate_own_account(
    client, db_session, superadmin_headers, test_superadmin_user
):
    """Deactivating the operator's own account would lock them out with no
    in-app recovery. Must refuse with 422."""
    resp = await client.post(
        f"/api/admin/users/{test_superadmin_user.id}/active",
        json={"active": False, "reason": "oops, wrong row"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422
    await db_session.refresh(test_superadmin_user)
    assert test_superadmin_user.is_active is True

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "user.deactivate"
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_can_still_reactivate_own_account(
    db_session, test_superadmin_user
):
    """The refusal only blocks the DEACTIVATE direction — reactivating
    (which can only ever help) must still work.

    Exercised at the SERVICE layer, not through the HTTP client, for the
    same reason as test_can_still_reinstate_own_family: a deactivated
    account can't authenticate at all (get_current_user checks is_active on
    every request), so there is no way to demonstrate this through the
    operator's own HTTP session — that IS the no-in-app-recovery problem
    this whole fix exists to prevent one from causing.
    """
    from app.services.admin.admin_action_service import AdminActionService

    test_superadmin_user.is_active = False
    await db_session.commit()

    result = await AdminActionService.set_user_active(
        db_session,
        operator=test_superadmin_user,
        user_id=test_superadmin_user.id,
        active=True,
        reason="reactivating",
    )
    assert result["is_active"] is True
    await db_session.refresh(test_superadmin_user)
    assert test_superadmin_user.is_active is True


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

    # Captured up front, before any rollback: db.rollback() inside
    # _record_failure expires every object on this shared session (see
    # release_paycheck/restore_recycled tests above for the same rule), so
    # re-reading test_family.id afterward would raise MissingGreenlet.
    family_id = test_family.id

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
            raise RuntimeError("grant credit exploded")
        return real_record(db, **kwargs)

    monkeypatch.setattr(
        OperatorAuditService, "record", staticmethod(_raise_once_then_record)
    )

    resp = await client.post(
        f"/api/admin/families/{family_id}/comp-plus",
        json={"days": 30, "reason": "force failure"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 500
    assert "grant credit failed" in resp.json()["detail"]

    # Restore the real refresh()/record() before using db_session ourselves
    # to verify final state below.
    monkeypatch.undo()

    assert await _active_credit_end(db_session, family_id) is None

    rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.grant_credit"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].result == "error"
    assert "grant credit exploded" in rows[0].error
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

    today = await family_local_today(db_session, test_family.id)
    template = await gig_template_factory(family=test_family)
    assignment = TaskAssignment(
        template_id=template.id,
        family_id=test_family.id,
        assigned_to=test_child_user.id,
        status=AssignmentStatus.COMPLETED,
        approval_status=ApprovalStatus.APPROVED,
        assigned_date=today,
        week_of=await current_week_monday(db_session, test_family.id),
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
    # Family-local, never date.today(): the money path resolves "this week" in
    # the family's timezone, so a runner-clock week can name a different bucket
    # than the one BankService counts chore units in (see conftest).
    today = await family_local_today(db_session, family_id)
    week_monday = await current_week_monday(db_session, family_id)

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
async def test_release_paycheck_is_atomic_with_its_audit_row(
    client, db_session, superadmin_headers, test_family, test_child_user,
    mandatory_template_factory, monkeypatch,
):
    """Fault-injection guard for the "stage-first" mechanism release_paycheck
    relies on. The audit "ok" row is staged (db.add, no commit) BEFORE
    calling BankService.release_chore_paycheck; that sub-service is
    documented to commit EXACTLY ONCE, at the very end, after every one of
    its mutations, so its single internal commit is what actually persists
    the staged row and the money mutation together, atomically. Nothing in
    the type system enforces that "commits exactly once, at the end"
    contract — this test is the enforcement.

    Forces PointTransaction.create_parent_adjustment — called from inside
    release_chore_paycheck's points_rate branch, AFTER CashService.
    credit_split_rows has already staged its ledger row on the session but
    BEFORE the function's one legitimate `await db.commit()` — to raise.
    Under the current, correct implementation nothing has been committed at
    that point, so rolling back must erase both the staged "ok" audit row
    and the partial CashTransaction row together with it (same rule as
    test_deactivate_user_is_atomic_with_its_audit_row above, applied to the
    money action). The explicit db_session.rollback() below reproduces what
    the real get_db dependency does on any uncaught exception in
    production — the test client's override_get_db (conftest.py) yields
    db_session directly and skips that cleanup, so without it this same,
    still-open session would show its own uncommitted, pending writes as if
    they had survived, which would prove nothing.

    Verified this actually discriminates (not just passes vacuously):
    temporarily inserted `await db.commit()` in
    backend/app/services/bank_service.py's release_chore_paycheck right
    after the `CashService.credit_split_rows(...)` call (before the
    points-conversion block) — an early commit that would durably persist
    the staged "ok" row and the partial ledger row before this test's
    injected failure even fires. With that break in place this test's
    `assert ok_rows == []` failed (a real "ok" row was found). Reverted
    before committing.
    """
    from app.models.cash_transaction import CashTransaction, CashTransactionType
    from app.models.operator_audit import OperatorAuditLog
    from app.models.point_transaction import PointTransaction
    from app.models.task_assignment import AssignmentStatus, TaskAssignment
    from app.services.bank_service import BankService

    family_id = test_family.id
    kid_id = test_child_user.id
    today = await family_local_today(db_session, family_id)
    week_monday = await current_week_monday(db_session, family_id)

    # points_rate mode is the only allowance mode whose release path writes
    # a SECOND mutation (the points-conversion PointTransaction) after the
    # cash ledger row and before the final commit — exactly the window this
    # test needs to inject a fault into.
    acct = await BankService.ensure_account(db_session, test_child_user)
    acct.allowance_mode = "points_rate"
    acct.allowance_cents = 0
    test_child_user.points = 50
    await db_session.commit()

    template = await mandatory_template_factory(family=test_family, points=30)
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

    def _boom(cls, **kwargs):
        raise RuntimeError("simulated failure between partial mutation and final commit")

    monkeypatch.setattr(PointTransaction, "create_parent_adjustment", classmethod(_boom))

    # release_paycheck's except clause only catches HTTPException (the
    # domain-validation failures release_chore_paycheck raises BEFORE any
    # mutation) — a plain RuntimeError injected mid-mutation is NOT caught
    # there, so it is never routed through _record_failure either. It
    # propagates all the way out; the default `client` fixture's transport
    # re-raises app exceptions rather than turning them into a response
    # (see no_raise_client in test_request_id_catchall.py for the opposite
    # choice), so it surfaces here instead of on a status code.
    with pytest.raises(RuntimeError, match="simulated failure"):
        await client.post(
            f"/api/admin/families/{family_id}/release-paycheck",
            json={
                "kid_id": str(kid_id),
                "week_of": week_monday.isoformat(),
                "reason": "fault-injection: atomicity check",
            },
            headers=superadmin_headers,
        )

    await db_session.rollback()

    ok_rows = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "bank.release_paycheck",
                OperatorAuditLog.result == "ok",
            )
        )
    ).scalars().all()
    assert ok_rows == []

    ledger_rows = (
        await db_session.execute(
            select(CashTransaction).where(
                CashTransaction.user_id == kid_id,
                CashTransaction.type == CashTransactionType.ALLOWANCE,
                CashTransaction.week_of == week_monday,
            )
        )
    ).scalars().all()
    assert ledger_rows == []


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


@pytest.mark.asyncio
async def test_operator_can_grant_a_lifetime_pro_credit(
    client, superadmin_headers, db_session, test_family
):
    """comp_plus_month could not do either half of this."""
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/credits",
        headers=superadmin_headers,
        json={"tier": "pro", "days": None, "reason": "founder"},
    )
    assert resp.status_code == 200
    assert resp.json()["tier"] == "pro"
    assert resp.json()["ends_at"] is None

    from app.services.plan_credit_service import PlanCreditService

    assert await PlanCreditService.floor_tier(db_session, test_family.id) == "pro"


@pytest.mark.asyncio
async def test_granting_credit_writes_an_audit_row(
    client, superadmin_headers, db_session, test_family
):
    await client.post(
        f"/api/admin/families/{test_family.id}/credits",
        headers=superadmin_headers,
        json={"tier": "plus", "days": 30, "reason": "support goodwill"},
    )

    row = (
        await db_session.execute(
            select(OperatorAuditLog).where(
                OperatorAuditLog.action == "family.grant_credit"
            )
        )
    ).scalars().first()
    assert row is not None
    assert row.params["tier"] == "plus"


@pytest.mark.asyncio
async def test_grant_credit_is_superadmin_only(client, auth_headers, test_family):
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/credits",
        headers=auth_headers,
        json={"tier": "pro", "days": None, "reason": "nope"},
    )
    assert resp.status_code == 404
