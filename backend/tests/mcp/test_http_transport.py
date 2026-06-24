import json

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.mcp.http import _extract_bearer


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_requires_bearer():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401


@pytest.mark.anyio
async def test_mcp_bad_token_unauthorized(monkeypatch, test_engine, db_session):
    """An unknown/revoked token resolves to None → 401, never a tool call."""
    import app.mcp.http as mcp_http

    test_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp_http, "AsyncSessionLocal", test_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": "Bearer mcp_deadbeefdeadbeef"},
        )
        assert r.status_code == 401


@pytest.mark.anyio
async def test_mcp_valid_token_handshake(monkeypatch, test_engine, db_session, family, parent_user):
    """A minted token authenticates and the transport completes an initialize.

    The /mcp ASGI app resolves tokens via app.mcp.http.AsyncSessionLocal (the
    real engine); in tests we point that at the test engine so the minted token
    is visible. Family scope comes only from the token — never the request body.
    """
    from app.services.jarvis_mcp_token_service import TokenService
    import app.mcp.http as mcp_http

    _, secret = await TokenService.mint(db_session, family.id, parent_user.id, "test")

    test_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp_http, "AsyncSessionLocal", test_maker)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {secret}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert r.status_code == 200
        body = json.loads(r.text)
        assert body["jsonrpc"] == "2.0"
        assert "result" in body
        assert body["result"]["serverInfo"]["name"] == "family-pg"


# ---------------------------------------------------------------------------
# FIX 3: _extract_bearer must scan ALL Authorization headers, not bail on first
# ---------------------------------------------------------------------------

def test_extract_bearer_skips_non_bearer_headers():
    """FIX 3: _extract_bearer must continue past non-Bearer Authorization headers."""
    scope = {
        "headers": [
            (b"authorization", b"Basic abc123"),
            (b"authorization", b"Bearer mcp_xyz"),
        ]
    }
    assert _extract_bearer(scope) == "mcp_xyz"


def test_extract_bearer_returns_none_when_no_bearer():
    """If no Authorization header has a Bearer prefix, return None."""
    scope = {
        "headers": [
            (b"authorization", b"Basic abc123"),
            (b"authorization", b"Digest realm=test"),
        ]
    }
    assert _extract_bearer(scope) is None


def test_extract_bearer_no_headers():
    """Empty headers returns None."""
    assert _extract_bearer({"headers": []}) is None


def test_extract_bearer_single_valid_bearer():
    """Normal case: single Bearer header is extracted correctly."""
    scope = {"headers": [(b"authorization", b"Bearer mcp_abc123")]}
    assert _extract_bearer(scope) == "mcp_abc123"
