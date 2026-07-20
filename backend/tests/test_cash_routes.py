"""Route tests for /api/cash (balance, family, payout, adjust)."""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": test_parent_user.email, "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": test_child_user.email, "password": "password123"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_payout_parent_only_partial_and_no_overdraw(
    client, db_session, test_family, test_parent_user, test_child_user, parent_headers
):
    test_child_user.cash_cents = 5000
    await db_session.commit()

    # Overdraw rejected.
    r = await client.post(
        f"/api/cash/{test_child_user.id}/payout",
        json={"amount_cents": 9999}, headers=parent_headers,
    )
    assert r.status_code == 400

    # Partial payout ok.
    r = await client.post(
        f"/api/cash/{test_child_user.id}/payout",
        json={"amount_cents": 2000}, headers=parent_headers,
    )
    assert r.status_code == 200
    assert r.json()["new_balance_cents"] == 3000


@pytest.mark.asyncio
async def test_payout_forbidden_for_child(
    client, db_session, test_child_user, child_headers
):
    test_child_user.cash_cents = 5000
    await db_session.commit()
    r = await client.post(
        f"/api/cash/{test_child_user.id}/payout",
        json={"amount_cents": 1000}, headers=child_headers,
    )
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_balance_endpoint_returns_summary(
    client, db_session, test_child_user, child_headers
):
    test_child_user.cash_cents = 4200
    await db_session.commit()
    r = await client.get("/api/cash/balance", headers=child_headers)
    assert r.status_code == 200
    assert r.json()["current_balance_cents"] == 4200


@pytest.mark.asyncio
async def test_family_endpoint_lists_kids(
    client, db_session, test_family, test_child_user, parent_headers
):
    test_child_user.cash_cents = 1500
    await db_session.commit()
    r = await client.get("/api/cash/family", headers=parent_headers)
    assert r.status_code == 200
    rows = r.json()
    kid = next((x for x in rows if x["user_id"] == str(test_child_user.id)), None)
    assert kid is not None
    assert kid["current_balance_cents"] == 1500


@pytest.mark.asyncio
async def test_family_endpoint_includes_gig_pills(
    client, db_session, test_family, test_parent_user, test_child_user, parent_headers,
):
    from app.models.gig import GigClaim, GigClaimStatus, GigOffering
    from app.services.cash_service import CashService

    offering = GigOffering(family_id=test_family.id, title="Barrer el patio", points=30)
    db_session.add(offering)
    await db_session.flush()
    claim = GigClaim(
        gig_id=offering.id, family_id=test_family.id, claimed_by=test_child_user.id,
        status=GigClaimStatus.APPROVED, points_awarded=30,
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)

    await CashService.award_gig_cash(
        db_session, test_child_user.id, test_family.id, None, 3000, "gig",
        gig_claim_id=claim.id,
    )
    await db_session.commit()

    r = await client.get("/api/cash/family", headers=parent_headers)
    assert r.status_code == 200
    kid = next(x for x in r.json() if x["user_id"] == str(test_child_user.id))
    assert len(kid["recent_gigs"]) == 1
    assert kid["recent_gigs"][0]["title"] == "Barrer el patio"
    assert kid["recent_gigs"][0]["amount_cents"] == 3000


@pytest.mark.asyncio
async def test_balance_endpoint_has_no_gig_pills(
    client, db_session, test_child_user, child_headers
):
    """recent_gigs is parent-view-only (/family) — the kid's own /balance
    stays unchanged, per spec (kid-facing pages untouched)."""
    r = await client.get("/api/cash/balance", headers=child_headers)
    assert r.status_code == 200
    assert r.json()["recent_gigs"] == []
