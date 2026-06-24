# backend/tests/mcp/test_confirm_flow.py
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from app.mcp.confirm import is_destructive
from app.services.jarvis_pending_action_service import PendingActionService
from app.mcp.context import McpContext
from app.models.budget import BudgetAccount
from app.models.jarvis_pending_action import JarvisPendingAction


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_delete_is_destructive_create_is_not():
    assert is_destructive("budget_account_delete") is True
    assert is_destructive("budget_account_create") is False


@pytest.mark.anyio
async def test_approve_executes_once_reject_discards(db_session, family, parent_user):
    # seed an account to delete
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    acc = BudgetAccount(family_id=family.id, name="Doomed", type="checking")
    db_session.add(acc); await db_session.commit(); await db_session.refresh(acc)

    pa = await PendingActionService.create(db_session, ctx, "budget_account_delete", {"id": str(acc.id)})
    assert pa.status == "pending"
    # not executed yet
    assert await db_session.get(BudgetAccount, acc.id) is not None

    result = await PendingActionService.approve(db_session, pa.id, parent_user)
    assert result["ok"] is True
    assert await db_session.get(BudgetAccount, acc.id) is None

    # second approve is a no-op error (already resolved)
    with pytest.raises(Exception):
        await PendingActionService.approve(db_session, pa.id, parent_user)


@pytest.mark.anyio
async def test_cross_family_approve_denied(db_session, family, other_family, parent_user, other_parent):
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    pa = await PendingActionService.create(db_session, ctx, "budget_account_delete", {"id": str(uuid4())})
    with pytest.raises(Exception):
        await PendingActionService.approve(db_session, pa.id, other_parent)  # different family


# ---------------------------------------------------------------------------
# Bug #1 TDD: approve() must honor dispatch result (ok:False must NOT mark approved)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_approve_dispatch_failure_leaves_row_pending(db_session, family, parent_user):
    """When dispatch returns ok:False (e.g. target already deleted), approve()
    must raise and leave the row in 'pending' status — NOT mark it 'approved'."""
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)

    # Target a nonexistent account id — dispatch will return {"ok": False, ...}
    nonexistent_id = str(uuid4())
    pa = await PendingActionService.create(
        db_session, ctx, "budget_account_delete", {"id": nonexistent_id}
    )
    assert pa.status == "pending"

    # approve() must raise when dispatch fails
    with pytest.raises(Exception) as exc_info:
        await PendingActionService.approve(db_session, pa.id, parent_user)

    # The row must still be pending (not silently approved)
    await db_session.refresh(pa)
    assert pa.status == "pending", (
        f"Row was set to '{pa.status}' even though dispatch failed: {exc_info.value}"
    )


# ---------------------------------------------------------------------------
# Bug #2 TDD: list_pending() must exclude expired rows
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_pending_excludes_expired(db_session, family, parent_user):
    """list_pending must NOT return rows whose expires_at is in the past."""
    # Seed an expired pending action directly (bypass service to control expires_at)
    expired_pa = JarvisPendingAction(
        family_id=family.id,
        user_id=parent_user.id,
        tool_name="budget_account_delete",
        params={"id": str(uuid4())},
        summary="expired action",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # already expired
    )
    db_session.add(expired_pa)

    # Seed a valid (non-expired) pending action
    ctx = McpContext(family_id=family.id, user_id=parent_user.id, role="PARENT", db=db_session)
    valid_pa = await PendingActionService.create(
        db_session, ctx, "budget_account_create", {"name": "New account", "type": "checking"}
    )

    await db_session.commit()
    await db_session.refresh(expired_pa)

    rows = await PendingActionService.list_pending(db_session, family.id)
    ids = [r.id for r in rows]

    assert valid_pa.id in ids, "Valid pending action must appear in list"
    assert expired_pa.id not in ids, "Expired action must be excluded from list"


# ---------------------------------------------------------------------------
# FIX 4: approve() must raise the SAME "expired" error on first AND second call
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_approve_expired_pending_row_raises_expired_first_call(db_session, family, parent_user):
    """FIX 4: approving an expired-but-still-pending row must raise 'Action has expired'."""
    expired_pa = JarvisPendingAction(
        family_id=family.id,
        user_id=parent_user.id,
        tool_name="budget_account_delete",
        params={"id": str(uuid4())},
        summary="expired action",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(expired_pa)
    await db_session.commit()
    await db_session.refresh(expired_pa)

    with pytest.raises(ValueError, match="Action has expired"):
        await PendingActionService.approve(db_session, expired_pa.id, parent_user)

    # Row must now be marked expired
    await db_session.refresh(expired_pa)
    assert expired_pa.status == "expired"


@pytest.mark.anyio
async def test_approve_expired_row_second_call_same_error(db_session, family, parent_user):
    """FIX 4: second approve() on an already-expired row must raise the SAME error."""
    expired_pa = JarvisPendingAction(
        family_id=family.id,
        user_id=parent_user.id,
        tool_name="budget_account_delete",
        params={"id": str(uuid4())},
        summary="already expired",
        status="pending",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(expired_pa)
    await db_session.commit()
    await db_session.refresh(expired_pa)

    # First call: transitions pending→expired, raises "Action has expired"
    with pytest.raises(ValueError, match="Action has expired"):
        await PendingActionService.approve(db_session, expired_pa.id, parent_user)

    # Second call: row is already status="expired"; must raise the SAME error
    with pytest.raises(ValueError, match="Action has expired"):
        await PendingActionService.approve(db_session, expired_pa.id, parent_user)
