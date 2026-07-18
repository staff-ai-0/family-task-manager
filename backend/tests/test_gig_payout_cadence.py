import pytest
from httpx import AsyncClient
from app.models.gig import GigOffering, GigPayoutCadence


def test_payout_cadence_enum_values():
    assert {c.value for c in GigPayoutCadence} == {
        "immediate", "weekly", "biweekly", "monthly",
    }


def test_gig_offering_has_payout_cadence_column():
    assert "payout_cadence" in GigOffering.__table__.columns


# ── API round-trip (offering create) ─────────────────────────────────────────
# NOTE: the brief pointed at tests/test_gigs.py for the parent-auth client
# fixtures, but that file doesn't exist in this repo. The verified equivalent
# is tests/test_gig_board.py, which exercises this same POST /api/gigs/offerings
# endpoint via the global `client` fixture (conftest.py) + a parent-login
# headers fixture. conftest.py already exposes that exact pattern as
# `auth_headers` (logs in as test_parent_user), so it's reused here rather
# than adding a duplicate local fixture.

@pytest.mark.asyncio
async def test_create_gig_with_weekly_cadence_roundtrips(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/gigs/offerings",
        json={"title": "Lavar el coche", "points": 50, "payout_cadence": "weekly"},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201)
    assert resp.json()["payout_cadence"] == "weekly"


@pytest.mark.asyncio
async def test_create_gig_defaults_cadence_immediate(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/gigs/offerings",
        json={"title": "Sacar basura", "points": 10},
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201)
    assert resp.json()["payout_cadence"] == "immediate"


@pytest.mark.asyncio
async def test_create_gig_rejects_bad_cadence(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/gigs/offerings",
        json={"title": "x", "points": 10, "payout_cadence": "hourly"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
