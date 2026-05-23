"""Tests for the one-time gigs-intro banner ack endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_new_user_default_false(client: AsyncClient, auth_headers):
    r = await client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["acknowledged_gigs_intro"] is False


@pytest.mark.asyncio
async def test_ack_sets_flag_true(client: AsyncClient, auth_headers):
    r = await client.post("/api/auth/ack-gigs-intro", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["acknowledged_gigs_intro"] is True

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["acknowledged_gigs_intro"] is True


@pytest.mark.asyncio
async def test_ack_idempotent(client: AsyncClient, auth_headers):
    r1 = await client.post("/api/auth/ack-gigs-intro", headers=auth_headers)
    r2 = await client.post("/api/auth/ack-gigs-intro", headers=auth_headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["acknowledged_gigs_intro"] is True


@pytest.mark.asyncio
async def test_ack_requires_auth(client: AsyncClient):
    r = await client.post("/api/auth/ack-gigs-intro")
    assert r.status_code in (401, 403)
