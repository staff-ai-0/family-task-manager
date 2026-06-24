import pytest
from datetime import datetime, timedelta, timezone
from app.models.jarvis_pending_action import JarvisPendingAction


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_pending_action_persists(db_session, family, parent_user):
    pa = JarvisPendingAction(
        family_id=family.id, user_id=parent_user.id, tool_name="budget_account_delete",
        params={"id": "x"}, summary="delete account", status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db_session.add(pa)
    await db_session.commit()
    await db_session.refresh(pa)
    assert pa.id is not None and pa.status == "pending"
