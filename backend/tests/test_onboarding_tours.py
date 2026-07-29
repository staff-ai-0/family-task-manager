"""Per-module tour completion flags.

The welcome tour has exactly one boolean (`users.completed_welcome_tour`), which
is why every module tour would otherwise fire forever or never. These cover the
per-tour list that replaces it for module tours: it must accumulate, stay
idempotent, reject ids the frontend does not define, work for kids as well as
parents, and never leak across users.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


TOUR = "/api/families/onboarding/tours"


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    response = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_completed_tours_starts_empty(client, auth_headers):
    r = await client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["completed_tours"] == []


@pytest.mark.asyncio
async def test_completing_a_tour_shows_up_on_me(client, auth_headers):
    r = await client.post(f"{TOUR}/budget-parent/complete", headers=auth_headers)
    assert r.status_code == 204

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["completed_tours"] == ["budget-parent"]


@pytest.mark.asyncio
async def test_completing_twice_does_not_duplicate(client, auth_headers):
    # The ack fires by sendBeacon on every exit path, and a replay acks again —
    # appending blindly would grow the row without bound.
    for _ in range(3):
        r = await client.post(f"{TOUR}/budget-parent/complete", headers=auth_headers)
        assert r.status_code == 204

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["completed_tours"] == ["budget-parent"]


@pytest.mark.asyncio
async def test_tours_accumulate(client, auth_headers):
    await client.post(f"{TOUR}/budget-parent/complete", headers=auth_headers)
    await client.post(f"{TOUR}/chores-parent/complete", headers=auth_headers)

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert sorted(me.json()["completed_tours"]) == ["budget-parent", "chores-parent"]


@pytest.mark.asyncio
async def test_unknown_tour_id_is_rejected(client, auth_headers):
    # Fail closed on ids the frontend does not define: without an allowlist
    # this is a user-controlled write into a JSONB column on every request.
    r = await client.post(f"{TOUR}/not-a-tour/complete", headers=auth_headers)
    assert r.status_code == 422

    me = await client.get("/api/auth/me", headers=auth_headers)
    assert me.json()["completed_tours"] == []


@pytest.mark.asyncio
async def test_a_kid_can_complete_a_kid_tour(client, child_headers):
    # The gig-board and rewards tours are kid-facing, so this route cannot be
    # parent-gated like the rest of the onboarding router.
    r = await client.post(f"{TOUR}/rewards-kid/complete", headers=child_headers)
    assert r.status_code == 204

    me = await client.get("/api/auth/me", headers=child_headers)
    assert me.json()["completed_tours"] == ["rewards-kid"]


@pytest.mark.asyncio
async def test_one_members_tours_do_not_appear_on_another(
    client, auth_headers, child_headers
):
    await client.post(f"{TOUR}/budget-parent/complete", headers=auth_headers)

    kid = await client.get("/api/auth/me", headers=child_headers)
    assert kid.json()["completed_tours"] == []


@pytest.mark.asyncio
async def test_requires_authentication(client):
    r = await client.post(f"{TOUR}/budget-parent/complete")
    assert r.status_code in (401, 403)
