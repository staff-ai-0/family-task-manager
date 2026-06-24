# backend/tests/mcp/test_confirm_flow.py
import pytest
from uuid import uuid4
from app.mcp.confirm import is_destructive
from app.services.jarvis_pending_action_service import PendingActionService
from app.mcp.context import McpContext
from app.models.budget import BudgetAccount


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
