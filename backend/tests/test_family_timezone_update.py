"""Tests for parent-only family timezone update endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_parent_updates_timezone(client: AsyncClient, auth_headers, test_family):
    r = await client.patch(
        "/api/families/me",
        json={"timezone": "America/Mexico_City"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "America/Mexico_City"

    # GET should now return the new tz
    me = await client.get("/api/families/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["timezone"] == "America/Mexico_City"


@pytest.mark.asyncio
async def test_invalid_timezone_rejected(client: AsyncClient, auth_headers):
    r = await client.patch(
        "/api/families/me",
        json={"timezone": "Mars/Olympus_Mons"},
        headers=auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_child_cannot_update_family(client: AsyncClient, test_child_user):
    # Login as child
    login = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = await client.patch(
        "/api/families/me",
        json={"timezone": "America/Mexico_City"},
        headers=headers,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_get_my_family_exposes_timezone(client: AsyncClient, auth_headers):
    r = await client.get("/api/families/me", headers=auth_headers)
    assert r.status_code == 200
    # Default seed value
    assert "timezone" in r.json()
