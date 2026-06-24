"""Tests for restricted DB role hardening (Task 11).

The ``jarvis_mcp`` PostgreSQL role (created by migration
``2026_06_24_mcp_restricted_role``) is granted CRUD on activity-domain tables
only.  It has NO grants on ``users``, ``families``, ``*subscription*``, or
billing/auth tables.

These tests are **skipped** when the role is not provisioned in the test DB,
because the test DB is managed by SQLAlchemy DDL and does not run the Alembic
migration that creates the role.  Set ``JARVIS_MCP_DB_ROLE=jarvis_mcp`` in the
test env AND have the DBA pre-create the role in the test DB to enable the
live guard.

What is tested unconditionally:
- ``_quote_ident`` defensively escapes the role name (unit test, no DB).
- When ``JARVIS_MCP_DB_ROLE`` is set, ``http.py`` executes ``SET ROLE`` on the
  session (via a real HTTP call through ``mcp_asgi`` with the session factory
  monkeypatched to capture statements).
- When ``JARVIS_MCP_DB_ROLE`` is unset, the warning log fires (verified by the
  same real HTTP call path).

What is tested only when the role is live:
- A session running as ``jarvis_mcp`` can SELECT from ``budget_accounts``.
- A session running as ``jarvis_mcp`` CANNOT SELECT from ``users``.
"""

import logging
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROLE_ENV = "JARVIS_MCP_DB_ROLE"
_ROLE_NAME = os.getenv(_ROLE_ENV, "")

_ROLE_LIVE = bool(_ROLE_NAME)


def _skip_if_no_role(reason: str = "JARVIS_MCP_DB_ROLE not set or role not provisioned"):
    return pytest.mark.skipif(not _ROLE_LIVE, reason=reason)


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------


def test_quote_ident_normal():
    """_quote_ident wraps a plain identifier in double-quotes."""
    from app.mcp.http import _quote_ident

    assert _quote_ident("jarvis_mcp") == '"jarvis_mcp"'


def test_quote_ident_escapes_embedded_quote():
    """_quote_ident escapes an embedded double-quote (SQL injection guard)."""
    from app.mcp.http import _quote_ident

    assert _quote_ident('bad"role') == '"bad""role"'


# ---------------------------------------------------------------------------
# SET ROLE wiring — calls the real mcp_asgi via HTTP; always runs
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _SpySession:
    """Thin async context-manager wrapper around a real SQLAlchemy session.

    Intercepts every ``execute`` call so tests can assert on the SQL strings
    that ``mcp_asgi`` actually dispatches to the DB session.

    ``SET ROLE`` and ``RESET ROLE`` are captured but *not* forwarded to the
    real DB connection — the test DB does not have the ``jarvis_mcp`` role, so
    forwarding would raise.  All other statements are delegated normally so the
    rest of the MCP request flow (tool dispatch, etc.) continues.
    """

    _ROLE_STMTS = ("SET ROLE", "RESET ROLE")

    def __init__(self, real: AsyncSession, log: list[str]) -> None:
        self._real = real
        self._log = log

    async def execute(self, stmt, *args, **kwargs):
        sql_str = str(stmt)
        self._log.append(sql_str)
        # Don't forward SET/RESET ROLE to the test DB — the role does not exist
        # there.  Returning None mimics a successful DDL execution from
        # mcp_asgi's perspective (the return value is not used).
        if any(sql_str.strip().upper().startswith(tok) for tok in self._ROLE_STMTS):
            return None
        return await self._real.execute(stmt, *args, **kwargs)

    def __getattr__(self, name: str):
        # Delegate all other attribute access to the wrapped session
        return getattr(self._real, name)

    async def __aenter__(self):
        await self._real.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._real.__aexit__(*exc_info)


def _make_spy_factory(base_maker: async_sessionmaker, spy_log: list[str]):
    """Return a callable that behaves like ``async_sessionmaker``.

    The *first* call (auth lookup session) yields a plain session so token
    resolution succeeds.  The *second* call (request session) wraps the session
    in ``_SpySession`` so ``SET ROLE`` / warning-branch executions are captured.
    """
    call_count = 0

    class _SpyFactory:
        def __call__(self):
            nonlocal call_count
            call_count += 1
            real = base_maker()
            if call_count >= 2:
                # Request session — spy on execute()
                return _SpySession(real, spy_log)
            return real

    return _SpyFactory()


@pytest.mark.anyio
async def test_set_role_called_when_role_configured(
    monkeypatch, test_engine, db_session, family, parent_user
):
    """mcp_asgi executes SET ROLE on the request session when JARVIS_MCP_DB_ROLE is set.

    This test calls the *real* ``mcp_asgi`` ASGI app via an HTTP request.
    ``AsyncSessionLocal`` in ``app.mcp.http`` is monkeypatched so sessions use
    the test engine; a spy wrapper records every SQL statement executed on the
    second (request) session.  If someone removes ``SET ROLE`` from ``http.py``
    this test will fail because the spy log will contain no matching statement.
    """
    import app.mcp.http as mcp_http
    from app.core.config import settings
    from app.main import app
    from app.services.jarvis_mcp_token_service import TokenService

    # Mint a real token so the auth session resolves successfully.
    _, secret = await TokenService.mint(db_session, family.id, parent_user.id, "role-test")

    executed_statements: list[str] = []
    base_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    spy_factory = _make_spy_factory(base_maker, executed_statements)

    monkeypatch.setattr(mcp_http, "AsyncSessionLocal", spy_factory)
    monkeypatch.setattr(settings, "JARVIS_MCP_DB_ROLE", "jarvis_mcp")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post(
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

    assert any(
        "SET ROLE" in s and "jarvis_mcp" in s for s in executed_statements
    ), (
        f"Expected 'SET ROLE \"jarvis_mcp\"' in executed statements; got: {executed_statements}"
    )


@pytest.mark.anyio
async def test_warning_logged_when_role_unset(
    monkeypatch, caplog, test_engine, db_session, family, parent_user
):
    """mcp_asgi emits a warning when JARVIS_MCP_DB_ROLE is None.

    This test calls the *real* ``mcp_asgi`` ASGI app via an HTTP request.
    ``AsyncSessionLocal`` in ``app.mcp.http`` is monkeypatched so sessions use
    the test engine; ``JARVIS_MCP_DB_ROLE`` is cleared so the warning branch
    executes.  Removing the warning from ``http.py`` will cause this test to
    fail because no matching log record will appear.
    """
    import app.mcp.http as mcp_http
    from app.core.config import settings
    from app.main import app
    from app.services.jarvis_mcp_token_service import TokenService

    # Mint a real token so the auth session resolves successfully.
    _, secret = await TokenService.mint(db_session, family.id, parent_user.id, "role-test-warn")

    base_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(mcp_http, "AsyncSessionLocal", base_maker)
    monkeypatch.setattr(settings, "JARVIS_MCP_DB_ROLE", None)

    transport = ASGITransport(app=app)
    with caplog.at_level(logging.WARNING, logger="app.mcp.http"):
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            await c.post(
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

    assert any(
        "JARVIS_MCP_DB_ROLE unset" in r.message
        for r in caplog.records
        if r.name == "app.mcp.http"
    ), f"Expected 'JARVIS_MCP_DB_ROLE unset' warning; got records: {[r.message for r in caplog.records]}"


# ---------------------------------------------------------------------------
# Live role tests — skipped unless role is provisioned in the test DB
# ---------------------------------------------------------------------------


@_skip_if_no_role()
@pytest.mark.anyio
async def test_jarvis_mcp_role_can_read_activity_table(db_session):
    """jarvis_mcp role can SELECT from budget_accounts."""
    await db_session.execute(text(f"SET ROLE {_ROLE_NAME}"))
    # Should not raise
    result = await db_session.execute(text("SELECT 1 FROM budget_accounts LIMIT 1"))
    await db_session.execute(text("RESET ROLE"))


@_skip_if_no_role()
@pytest.mark.anyio
async def test_jarvis_mcp_role_cannot_read_users(db_session):
    """jarvis_mcp role must NOT be able to SELECT from users."""
    import asyncpg

    await db_session.execute(text(f"SET ROLE {_ROLE_NAME}"))
    try:
        with pytest.raises(Exception, match="permission denied"):
            await db_session.execute(text("SELECT 1 FROM users LIMIT 1"))
    finally:
        await db_session.execute(text("RESET ROLE"))


@_skip_if_no_role()
@pytest.mark.anyio
async def test_jarvis_mcp_role_cannot_read_subscriptions(db_session):
    """jarvis_mcp role must NOT be able to SELECT from family_subscriptions."""
    await db_session.execute(text(f"SET ROLE {_ROLE_NAME}"))
    try:
        with pytest.raises(Exception, match="permission denied"):
            await db_session.execute(
                text("SELECT 1 FROM family_subscriptions LIMIT 1")
            )
    finally:
        await db_session.execute(text("RESET ROLE"))
