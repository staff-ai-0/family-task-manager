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
