"""Permanent member deletion is gated: deactivate first + typed confirmation.

Regression: the Members-page Delete button hard-deleted the account (with
CASCADE across assignments/points) on a single browser confirm() — a real kid
account was lost this way and had to be restored from a pg_dump. Permanent
deletion now requires the member to already be deactivated AND the request to
carry ``confirm=<member name>``.
"""

import pytest


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_delete_active_member_is_blocked(
    client, db_session, test_family, test_parent_user, test_child_user
):
    headers = await _login(client, test_parent_user.email)
    r = await client.delete(
        f"/api/users/{test_child_user.id}?confirm=Test%20Child",
        headers=headers,
    )
    assert r.status_code == 400
    body = r.json()
    assert "deactivate" in (body.get("message") or body.get("detail") or "").lower()


@pytest.mark.asyncio
async def test_delete_without_confirmation_is_blocked(
    client, db_session, test_family, test_parent_user, test_child_user
):
    from app.services.auth_service import AuthService

    await AuthService.deactivate_user(db_session, test_child_user.id)
    headers = await _login(client, test_parent_user.email)

    r = await client.delete(
        f"/api/users/{test_child_user.id}", headers=headers
    )
    assert r.status_code == 400

    r = await client.delete(
        f"/api/users/{test_child_user.id}?confirm=wrong%20name",
        headers=headers,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_deactivated_member_with_typed_name_succeeds(
    client, db_session, test_family, test_parent_user, test_child_user
):
    from sqlalchemy import select
    from app.models.user import User
    from app.services.auth_service import AuthService

    await AuthService.deactivate_user(db_session, test_child_user.id)
    headers = await _login(client, test_parent_user.email)

    r = await client.delete(
        f"/api/users/{test_child_user.id}?confirm=Test%20Child",
        headers=headers,
    )
    assert r.status_code == 204, r.text

    gone = (await db_session.execute(
        select(User).where(User.id == test_child_user.id)
    )).scalar_one_or_none()
    assert gone is None
