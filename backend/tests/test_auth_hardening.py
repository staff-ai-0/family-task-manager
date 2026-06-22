"""M3 auth hardening — deactivated accounts must not authenticate.

Login already rejects deactivated users (auth_service), but the access-token
path (`get_current_user`) did not re-check `is_active`, so a still-valid
access token (<=60 min) kept working after an account was disabled.
"""
import pytest
from fastapi import HTTPException

from app.core.security import create_access_token
from app.core.dependencies import get_current_user


@pytest.mark.asyncio
async def test_deactivated_user_access_token_rejected(db_session, test_parent_user):
    test_parent_user.is_active = False
    await db_session.commit()

    token = create_access_token({"sub": str(test_parent_user.id)})
    with pytest.raises(HTTPException) as exc:
        await get_current_user(token=token, db=db_session)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_active_user_access_token_accepted(db_session, test_parent_user):
    token = create_access_token({"sub": str(test_parent_user.id)})
    user = await get_current_user(token=token, db=db_session)
    assert user.id == test_parent_user.id
