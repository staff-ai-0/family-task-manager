"""Authorization matrix for the super-admin surface.

The rule under test: an operator needs BOTH users.is_superadmin AND an email
in SUPERADMIN_EMAILS. Either alone is insufficient, and every failure mode
must return 404 (not 403) so the surface is not discoverable.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import require_superadmin
from app.models.user import User


@pytest.mark.asyncio
async def test_require_superadmin_accepts_flag_and_allowlist(
    client: AsyncClient, superadmin_headers: dict
):
    resp = await client.get("/api/admin/ping", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_require_superadmin_rejects_flag_without_allowlist(
    client: AsyncClient, db_session, test_superadmin_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", [])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "superadmin@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_allowlist_without_flag(
    client: AsyncClient, db_session, test_parent_user: User, monkeypatch
):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAILS", ["parent@test.com"])
    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    token = resp.json()["access_token"]
    resp = await client.get(
        "/api/admin/ping", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_plain_parent(
    client: AsyncClient, auth_headers: dict, allowlist_superadmin
):
    resp = await client.get("/api/admin/ping", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_require_superadmin_rejects_anonymous(client: AsyncClient):
    resp = await client.get("/api/admin/ping")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_family_detail_never_leaks_other_family_members(
    client, db_session, superadmin_headers, test_family
):
    """The operator asks for family A and gets ONLY family A."""
    from app.core.security import get_password_hash
    from app.models.family import Family
    from app.models.user import User, UserRole

    other = Family(name="Other Family")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    db_session.add(
        User(
            email="outsider@test.com",
            password_hash=get_password_hash("password123"),
            name="Outsider",
            role=UserRole.PARENT,
            family_id=other.id,
            email_verified=True,
        )
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=superadmin_headers
    )
    emails = {m["email"] for m in resp.json()["members"]}
    assert "outsider@test.com" not in emails


@pytest.mark.asyncio
async def test_family_detail_rejects_parent_of_that_family(
    client, auth_headers, test_family, allowlist_superadmin
):
    """A parent cannot read their OWN family through the admin surface."""
    resp = await client.get(
        f"/api/admin/families/{test_family.id}", headers=auth_headers
    )
    assert resp.status_code == 404
