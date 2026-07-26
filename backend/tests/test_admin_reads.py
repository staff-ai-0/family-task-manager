"""Admin read surfaces and the instrumentation they depend on."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_last_seen_at_stamped_on_authenticated_request(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at is not None


@pytest.mark.asyncio
async def test_last_seen_at_not_rewritten_within_throttle_window(
    client, db_session, auth_headers, test_parent_user
):
    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    first = test_parent_user.last_seen_at

    await client.get("/api/auth/me", headers=auth_headers)
    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at == first


@pytest.mark.asyncio
async def test_last_seen_at_rewritten_once_throttle_elapses(
    client, db_session, auth_headers, test_parent_user
):
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    test_parent_user.last_seen_at = stale
    await db_session.commit()

    await client.get("/api/auth/me", headers=auth_headers)
    refreshed = (
        await db_session.execute(
            select(User).where(User.id == test_parent_user.id)
        )
    ).scalar_one()
    assert refreshed.last_seen_at > stale


@pytest.mark.asyncio
async def test_last_seen_write_failure_does_not_break_request(
    client, db_session, auth_headers, test_parent_user, monkeypatch
):
    """The activity stamp is best-effort: if the write inside
    _touch_last_seen fails, the request must still succeed AND the user
    object must still be usable by downstream code (route handlers read
    attributes synchronously — e.g. UserResponse.model_validate(current_user)
    in GET /api/auth/me) — with no further unguarded database IO on the
    failure path.

    Poisons both the UPDATE on `users` (the primary write attempt) AND
    AsyncSession.refresh on this same user instance (the residual recovery
    call a rollback-then-refresh fix would issue). AsyncSession.refresh is
    implemented via greenlet_spawn(sync_session.refresh, ...) — it does not
    go through AsyncSession.execute — so a fix that depends on refresh()
    succeeding after a failed write is not exercised by patching execute()
    alone; this simulates a dead-connection-style failure where that
    recovery read would also fail. The correct fix (a SAVEPOINT whose
    rollback never expires `user` in the first place) needs no recovery
    read at all and never calls refresh(), so it is unaffected.
    """
    original_execute = AsyncSession.execute
    original_refresh = AsyncSession.refresh

    async def failing_execute(self, statement, *args, **kwargs):
        if isinstance(statement, Update) and statement.table.name == "users":
            raise RuntimeError("simulated last_seen_at write failure")
        return await original_execute(self, statement, *args, **kwargs)

    async def failing_refresh(self, instance, *args, **kwargs):
        if instance is test_parent_user:
            raise RuntimeError("simulated dead-connection refresh failure")
        return await original_refresh(self, instance, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)
    monkeypatch.setattr(AsyncSession, "refresh", failing_refresh)

    response = await client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["email"] == test_parent_user.email


@pytest.mark.asyncio
async def test_last_seen_at_naive_stored_value_does_not_break_request(
    client, db_session, auth_headers, test_parent_user
):
    """A naive (tzinfo-less) last_seen_at should never reach the column via
    SQLAlchemy, but if one ever did (e.g. a raw-SQL backfill/import script),
    comparing it against an aware `now` must not raise an unhandled
    TypeError — the stamp is best-effort and must degrade gracefully."""
    test_parent_user.last_seen_at = datetime(2020, 1, 1)  # naive
    await db_session.commit()

    response = await client.get("/api/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["email"] == test_parent_user.email
