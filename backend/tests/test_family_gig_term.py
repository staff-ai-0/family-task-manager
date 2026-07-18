"""Tests for the per-family gig term (gig | chamba).

DB tables/routes/code identifiers stay "gig" — this only controls the
user-visible copy rendered on the gig-board surface. Fixtures follow the
pattern in test_family_timezone_update.py (client + auth_headers; there is
no `parent_client` fixture in conftest.py).
"""
import pytest
from httpx import AsyncClient


def test_family_has_gig_term_column():
    from app.models.family import Family

    assert "gig_term" in Family.__table__.columns


@pytest.mark.asyncio
async def test_gig_term_defaults_to_gig(client: AsyncClient, auth_headers):
    resp = await client.get("/api/families/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["gig_term"] == "gig"


@pytest.mark.asyncio
async def test_parent_can_set_gig_term_to_chamba(client: AsyncClient, auth_headers):
    resp = await client.patch(
        "/api/families/me", json={"gig_term": "chamba"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["gig_term"] == "chamba"

    # GET should now reflect the change too.
    me = await client.get("/api/families/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["gig_term"] == "chamba"


@pytest.mark.asyncio
async def test_gig_term_rejects_bad_value(client: AsyncClient, auth_headers):
    resp = await client.patch(
        "/api/families/me", json={"gig_term": "trabajo"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_child_cannot_set_gig_term(client: AsyncClient, test_child_user):
    """Multi-tenant/auth regression: only parents may change family-wide
    settings (mirrors test_child_cannot_update_family in
    test_family_timezone_update.py) — gig_term must not weaken that gate."""
    login = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.patch(
        "/api/families/me", json={"gig_term": "chamba"}, headers=headers
    )
    assert resp.status_code == 403
