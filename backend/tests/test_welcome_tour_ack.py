"""Tests for the one-time welcome-tour ack endpoint."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_new_user_default_false(client: AsyncClient, auth_headers):
    r = await client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["completed_welcome_tour"] is False


@pytest.mark.asyncio
async def test_ack_sets_flag_true(client: AsyncClient, auth_headers):
    r = await client.post("/api/auth/ack-tour", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["completed_welcome_tour"] is True

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["completed_welcome_tour"] is True


@pytest.mark.asyncio
async def test_ack_idempotent(client: AsyncClient, auth_headers):
    r1 = await client.post("/api/auth/ack-tour", headers=auth_headers)
    r2 = await client.post("/api/auth/ack-tour", headers=auth_headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["completed_welcome_tour"] is True


@pytest.mark.asyncio
async def test_ack_requires_auth(client: AsyncClient):
    r = await client.post("/api/auth/ack-tour")
    assert r.status_code in (401, 403)
