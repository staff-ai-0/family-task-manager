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
