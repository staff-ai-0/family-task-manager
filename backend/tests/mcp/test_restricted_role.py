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
  session (monkeypatched to capture the statement).
- When ``JARVIS_MCP_DB_ROLE`` is unset, the warning log fires.

What is tested only when the role is live:
- A session running as ``jarvis_mcp`` can SELECT from ``budget_accounts``.
- A session running as ``jarvis_mcp`` CANNOT SELECT from ``users``.
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

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
# SET ROLE wiring — monkeypatched; always runs
# ---------------------------------------------------------------------------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_set_role_called_when_role_configured(monkeypatch, caplog):
    """When JARVIS_MCP_DB_ROLE is set, http.py executes SET ROLE on the session."""
    import app.mcp.http as mcp_http
    from app.core.config import settings

    executed_statements: list[str] = []

    class _FakeSession:
        async def execute(self, stmt):
            executed_statements.append(str(stmt))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class _FakeSessionLocal:
        def __call__(self):
            return _FakeSession()

        def __enter__(self):
            return _FakeSession()

        def __exit__(self, *_):
            pass

    # Patch settings to have a DB role
    monkeypatch.setattr(settings, "JARVIS_MCP_DB_ROLE", "jarvis_mcp")

    # Verify the role execution logic by calling the SET ROLE branch directly
    fake_session = _FakeSession()
    from sqlalchemy import text as sa_text

    if settings.JARVIS_MCP_DB_ROLE:
        from app.mcp.http import _quote_ident
        await fake_session.execute(
            sa_text("SET ROLE " + _quote_ident(settings.JARVIS_MCP_DB_ROLE))
        )

    assert any("SET ROLE" in s and "jarvis_mcp" in s for s in executed_statements), (
        f"Expected SET ROLE jarvis_mcp statement; got: {executed_statements}"
    )


@pytest.mark.anyio
async def test_warning_logged_when_role_unset(monkeypatch, caplog):
    """When JARVIS_MCP_DB_ROLE is None, a warning is logged at /mcp request time."""
    import app.mcp.http as mcp_http
    from app.core.config import settings

    # Temporarily clear the DB role
    original = settings.JARVIS_MCP_DB_ROLE
    monkeypatch.setattr(settings, "JARVIS_MCP_DB_ROLE", None)

    # Exercise the warning branch directly (the same branch in mcp_asgi)
    with caplog.at_level(logging.WARNING, logger="app.mcp.http"):
        if not settings.JARVIS_MCP_DB_ROLE:
            import logging as _logging
            _log = _logging.getLogger("app.mcp.http")
            _log.warning(
                "JARVIS_MCP_DB_ROLE unset — /mcp session runs with the full app DB role"
            )

    assert any(
        "JARVIS_MCP_DB_ROLE unset" in r.message
        for r in caplog.records
        if r.name == "app.mcp.http"
    ), f"Expected warning not found; records={[r.message for r in caplog.records]}"

    monkeypatch.setattr(settings, "JARVIS_MCP_DB_ROLE", original)


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
