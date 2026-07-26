"""families.is_active must actually lock a family out.

Before this change is_active was enforced in exactly two places (join-code
lookup and registration), so a "suspended" family kept using the entire app.
"""

import pytest


@pytest.mark.asyncio
async def test_suspended_family_cannot_log_in(
    client, db_session, test_family, test_parent_user
):
    test_family.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_existing_token_stops_working_once_family_suspended(
    client, db_session, auth_headers, test_family
):
    ok = await client.get("/api/auth/me", headers=auth_headers)
    assert ok.status_code == 200

    test_family.is_active = False
    await db_session.commit()

    blocked = await client.get("/api/auth/me", headers=auth_headers)
    assert blocked.status_code == 401


@pytest.mark.asyncio
async def test_unsuspending_restores_access(
    client, db_session, auth_headers, test_family
):
    test_family.is_active = False
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401

    test_family.is_active = True
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 200
