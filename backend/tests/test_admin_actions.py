"""Operator actions and their audit trail."""

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
    coverage — this pins the 422 and confirms nothing was written."""
    resp = await client.post(
        f"/api/admin/families/{test_family.id}/modules",
        json={"enabled_modules": ["budget", "not_a_real_module"], "reason": "x"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422

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
    # actually proves atomicity. Against the pre-fix code (AuthService
    # committing internally before the audit row was staged) this would be
    # False: the deactivation would already be durably committed.
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
