"""Tests for parent oversight: fixes + command center."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── A1: consequence create payload shape ─────────────────────────────────────

@pytest.mark.asyncio
async def test_consequence_create_new_payload_shape(
    client, parent_headers, test_family, test_child_user
):
    """The exact payload the fixed frontend form sends must succeed."""
    res = await client.post(
        "/api/consequences/",
        json={
            "title": "No tablet",
            "description": "Too much screen time",
            "applied_to_user": str(test_child_user.id),
            "restriction_type": "screen_time",
            "severity": "low",
            "duration_days": 3,
        },
        headers=parent_headers,
    )
    assert res.status_code in (200, 201), res.text
    data = res.json()
    assert data["applied_to_user"] == str(test_child_user.id)
    assert data["restriction_type"] == "screen_time"
    assert data["end_date"] is not None
