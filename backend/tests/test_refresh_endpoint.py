"""POST /api/auth/refresh — exchange a valid refresh token for a new pair."""
import pytest
from httpx import AsyncClient

from app.core.security import create_refresh_token, decode_token


def _bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_refresh_happy_path(client: AsyncClient, test_parent_user):
    refresh = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    resp = await client.post("/api/auth/refresh", headers=_bearer(refresh))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert decode_token(body["access_token"]).get("type") == "access"
    assert decode_token(body["refresh_token"]).get("type") == "refresh"


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client: AsyncClient, test_parent_user):
    from app.core.security import create_access_token
    access = create_access_token({"sub": str(test_parent_user.id)})
    resp = await client.post("/api/auth/refresh", headers=_bearer(access))
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_refresh_rejects_stale_version(client: AsyncClient, db_session, test_parent_user):
    stale = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    test_parent_user.token_version += 1
    await db_session.commit()
    resp = await client.post("/api/auth/refresh", headers=_bearer(stale))
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_logout_invalidates_refresh(client: AsyncClient, db_session, test_parent_user):
    refresh = create_refresh_token(str(test_parent_user.id), version=test_parent_user.token_version)
    # Authenticate logout with a valid access token.
    from app.core.security import create_access_token
    access = create_access_token({"sub": str(test_parent_user.id)})
    out = await client.post("/api/auth/logout", headers=_bearer(access))
    assert out.status_code == 200, out.text
    # The pre-logout refresh token must now be rejected.
    resp = await client.post("/api/auth/refresh", headers=_bearer(refresh))
    assert resp.status_code == 401, resp.text
