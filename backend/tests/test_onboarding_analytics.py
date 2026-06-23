"""Tests for onboarding funnel events + analytics."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_record_event_and_analytics(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/families/onboarding/events",
        headers=auth_headers,
        json={"event_type": "tour_completed", "step_index": 7},
    )
    assert r.status_code == 204

    a = await client.get(
        "/api/families/onboarding/analytics", headers=auth_headers
    )
    assert a.status_code == 200
    data = a.json()
    assert data["tour_completed"] >= 1
    assert any(m["tour_status"] == "completed" for m in data["members"])
    assert "checklist" in data
    assert data["total_members"] >= 1


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored(client: AsyncClient, auth_headers):
    r = await client.post(
        "/api/families/onboarding/events",
        headers=auth_headers,
        json={"event_type": "bogus"},
    )
    assert r.status_code == 204
    a = await client.get(
        "/api/families/onboarding/analytics", headers=auth_headers
    )
    assert a.status_code == 200


@pytest.mark.asyncio
async def test_skipped_vs_completed_precedence(client: AsyncClient, auth_headers):
    # A skip followed by a completion should read as completed (completed wins).
    await client.post(
        "/api/families/onboarding/events",
        headers=auth_headers,
        json={"event_type": "tour_skipped"},
    )
    await client.post(
        "/api/families/onboarding/events",
        headers=auth_headers,
        json={"event_type": "tour_completed"},
    )
    a = await client.get(
        "/api/families/onboarding/analytics", headers=auth_headers
    )
    data = a.json()
    assert any(m["tour_status"] == "completed" for m in data["members"])


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: AsyncClient):
    r = await client.get("/api/families/onboarding/analytics")
    assert r.status_code in (401, 403)
