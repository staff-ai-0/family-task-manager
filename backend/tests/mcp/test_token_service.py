import pytest
from app.services.jarvis_mcp_token_service import TokenService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mint_resolve_revoke(db_session, family, parent_user):
    row, secret = await TokenService.mint(db_session, family.id, parent_user.id, "laptop")
    assert secret.startswith("mcp_") and row.token_prefix == secret[:8]
    resolved = await TokenService.resolve(db_session, secret)
    assert resolved is not None and resolved.family_id == family.id
    await TokenService.revoke(db_session, row.id, family.id)
    assert await TokenService.resolve(db_session, secret) is None
