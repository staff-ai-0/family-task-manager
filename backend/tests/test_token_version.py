"""User.token_version backs refresh-token revocation."""
import pytest


@pytest.mark.asyncio
async def test_user_token_version_defaults_to_zero(db_session, test_parent_user):
    await db_session.refresh(test_parent_user)
    assert test_parent_user.token_version == 0
