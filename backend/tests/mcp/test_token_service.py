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


@pytest.mark.anyio
async def test_token_created_at_is_timezone_aware(db_session, family, parent_user):
    """FIX 2: JarvisMcpToken.created_at must be timezone-aware (not naive datetime)."""
    row, _ = await TokenService.mint(db_session, family.id, parent_user.id, "tz-test")
    await db_session.refresh(row)
    assert row.created_at is not None, "created_at must not be None"
    assert row.created_at.tzinfo is not None, (
        f"created_at must be timezone-aware, got {row.created_at!r}"
    )
