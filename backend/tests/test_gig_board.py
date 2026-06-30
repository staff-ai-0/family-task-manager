"""Tests for the new gig board system (gig_offerings + gig_claims)."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def parent_headers(client: AsyncClient, test_parent_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def child_headers(client: AsyncClient, test_child_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "child@test.com", "password": "password123"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def teen_headers(client: AsyncClient, test_teen_user) -> dict:
    res = await client.post(
        "/api/auth/login",
        json={"email": "teen@test.local", "password": "password123"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Offering CRUD ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parent_create_offering(client: AsyncClient, parent_headers, test_family):
    res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Wash the car", "points": 50, "difficulty": 2, "category": "chores"},
        headers=parent_headers,
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["title"] == "Wash the car"
    assert data["points"] == 50
    assert data["difficulty"] == 2


@pytest.mark.asyncio
async def test_child_cannot_create_offering(client: AsyncClient, child_headers):
    res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Test", "points": 10, "difficulty": 1},
        headers=child_headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_offerings_shows_my_claim(
    client: AsyncClient, parent_headers, child_headers, test_family
):
    # Parent creates gig
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Clean garage", "points": 30},
        headers=parent_headers,
    )
    assert create_res.status_code == 201
    gig_id = create_res.json()["id"]

    # Kid claims it
    claim_res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    assert claim_res.status_code == 201

    # List shows my_claim populated
    list_res = await client.get("/api/gigs/offerings", headers=child_headers)
    assert list_res.status_code == 200
    items = list_res.json()
    my_item = next((i for i in items if i["offering"]["id"] == gig_id), None)
    assert my_item is not None
    assert my_item["my_claim"] is not None
    assert my_item["my_claim"]["status"] == "claimed"


@pytest.mark.asyncio
async def test_edit_and_deactivate_offering(client: AsyncClient, parent_headers):
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Mow lawn", "points": 40},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    edit_res = await client.put(
        f"/api/gigs/offerings/{gig_id}",
        json={"points": 60},
        headers=parent_headers,
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["points"] == 60

    del_res = await client.delete(f"/api/gigs/offerings/{gig_id}", headers=parent_headers)
    assert del_res.status_code == 204

    # Deactivated offering no longer appears in list
    list_res = await client.get("/api/gigs/offerings", headers=parent_headers)
    ids = [i["offering"]["id"] for i in list_res.json()]
    assert gig_id not in ids


# ── Claim lifecycle ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claim_complete_approve_awards_points(
    client: AsyncClient, parent_headers, child_headers, test_child_user, db_session: AsyncSession
):
    # Create gig
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Cook dinner", "points": 25},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    # Child claims
    claim_res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    assert claim_res.status_code == 201
    claim_id = claim_res.json()["id"]

    # Child submits proof
    complete_res = await client.post(
        f"/api/gigs/claims/{claim_id}/complete",
        json={"proof_text": "Made pasta for everyone!"},
        headers=child_headers,
    )
    assert complete_res.status_code == 200
    assert complete_res.json()["status"] == "completed"

    # Parent approves
    approve_res = await client.post(
        f"/api/gigs/claims/{claim_id}/approve",
        json={"approved": True},
        headers=parent_headers,
    )
    assert approve_res.status_code == 200
    data = approve_res.json()
    assert data["status"] == "approved"
    assert data["points_awarded"] == 25  # gig value in pesos

    # Gigs pay CASH, not privilege points.
    await db_session.refresh(test_child_user)
    assert test_child_user.points == 100        # points unchanged
    assert test_child_user.cash_cents == 2500   # $25 → 2500 cents


@pytest.mark.asyncio
async def test_reject_claim_no_points(
    client: AsyncClient, parent_headers, child_headers, test_child_user, db_session: AsyncSession
):
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Rejected gig", "points": 20},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    claim_res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    claim_id = claim_res.json()["id"]

    await client.post(
        f"/api/gigs/claims/{claim_id}/complete",
        json={"proof_text": "done"},
        headers=child_headers,
    )

    reject_res = await client.post(
        f"/api/gigs/claims/{claim_id}/approve",
        json={"approved": False, "notes": "Not done properly"},
        headers=parent_headers,
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "rejected"

    await db_session.refresh(test_child_user)
    assert test_child_user.points == 100  # unchanged


@pytest.mark.asyncio
async def test_two_kids_claim_same_gig_independently(
    client: AsyncClient, parent_headers, child_headers, db_session: AsyncSession, test_family
):
    # Create a second child user with a valid email domain
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    kid2 = User(
        email="kid2@example.com",
        password_hash=get_password_hash("password123"),
        name="Kid Two",
        role=UserRole.CHILD,
        family_id=test_family.id,
        email_verified=True,
        points=0,
    )
    db_session.add(kid2)
    await db_session.commit()

    login_res = await client.post(
        "/api/auth/login",
        json={"email": "kid2@example.com", "password": "password123"},
    )
    assert login_res.status_code == 200, f"Kid2 login failed: {login_res.text}"
    kid2_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Help with groceries", "points": 15},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    child_claim = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    kid2_claim = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=kid2_headers)

    assert child_claim.status_code == 201
    assert kid2_claim.status_code == 201
    assert child_claim.json()["id"] != kid2_claim.json()["id"]


@pytest.mark.asyncio
async def test_duplicate_claim_rejected(
    client: AsyncClient, parent_headers, child_headers
):
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Unique gig", "points": 10},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    first = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    second = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_unclaim_removes_claim(
    client: AsyncClient, parent_headers, child_headers
):
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Unclaim test gig", "points": 10},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    claim_res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    claim_id = claim_res.json()["id"]

    unclaim_res = await client.post(f"/api/gigs/claims/{claim_id}/unclaim", headers=child_headers)
    assert unclaim_res.status_code == 204

    # Can now claim again
    reclaim = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    assert reclaim.status_code == 201


@pytest.mark.asyncio
async def test_parent_cannot_claim(
    client: AsyncClient, parent_headers
):
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Parent cannot claim", "points": 10},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]

    res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=parent_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_points_equal_gig_value(
    client: AsyncClient, parent_headers, child_headers, test_child_user, db_session: AsyncSession
):
    points_value = 75
    create_res = await client.post(
        "/api/gigs/offerings",
        json={"title": "Big job", "points": points_value},
        headers=parent_headers,
    )
    gig_id = create_res.json()["id"]
    initial_points = test_child_user.points
    initial_cash = test_child_user.cash_cents

    claim_res = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    claim_id = claim_res.json()["id"]
    await client.post(f"/api/gigs/claims/{claim_id}/complete", json={"proof_text": "done"}, headers=child_headers)
    await client.post(f"/api/gigs/claims/{claim_id}/approve", json={"approved": True}, headers=parent_headers)

    await db_session.refresh(test_child_user)
    # 1 pt = $1 MXN = 100 cents; gigs pay cash, points stay put.
    assert test_child_user.cash_cents == initial_cash + points_value * 100
    assert test_child_user.points == initial_points


async def _claim_complete_approve(client, parent_headers, child_headers, title, points, approve=True):
    create = await client.post(
        "/api/gigs/offerings", json={"title": title, "points": points}, headers=parent_headers
    )
    gig_id = create.json()["id"]
    claim = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    claim_id = claim.json()["id"]
    await client.post(f"/api/gigs/claims/{claim_id}/complete", json={"proof_text": "x"}, headers=child_headers)
    return await client.post(
        f"/api/gigs/claims/{claim_id}/approve", json={"approved": approve}, headers=parent_headers
    )


@pytest.mark.asyncio
async def test_streak_increments_on_approve_and_resets_on_reject(
    client: AsyncClient, parent_headers, child_headers, test_child_user, db_session: AsyncSession
):
    assert test_child_user.gig_trust_streak == 0
    await _claim_complete_approve(client, parent_headers, child_headers, "G1", 10)
    await db_session.refresh(test_child_user)
    assert test_child_user.gig_trust_streak == 1

    await _claim_complete_approve(client, parent_headers, child_headers, "G2", 10)
    await db_session.refresh(test_child_user)
    assert test_child_user.gig_trust_streak == 2

    # Rejection breaks the streak.
    await _claim_complete_approve(client, parent_headers, child_headers, "G3", 10, approve=False)
    await db_session.refresh(test_child_user)
    assert test_child_user.gig_trust_streak == 0


@pytest.mark.asyncio
async def test_auto_approve_when_streak_at_threshold(
    client: AsyncClient, parent_headers, child_headers, test_child_user, db_session: AsyncSession
):
    # Pre-seed streak at the threshold (GIG_AUTO_APPROVE_STREAK default 3).
    test_child_user.gig_trust_streak = 3
    db_session.add(test_child_user)
    await db_session.commit()

    create = await client.post(
        "/api/gigs/offerings", json={"title": "Trusted gig", "points": 40}, headers=parent_headers
    )
    gig_id = create.json()["id"]
    claim = await client.post(f"/api/gigs/offerings/{gig_id}/claim", headers=child_headers)
    claim_id = claim.json()["id"]

    # Completing alone should auto-approve (no parent action) for a trusted kid.
    complete = await client.post(
        f"/api/gigs/claims/{claim_id}/complete", json={"proof_text": "trusted"}, headers=child_headers
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "approved"
    assert complete.json()["points_awarded"] == 40

    await db_session.refresh(test_child_user)
    assert test_child_user.gig_trust_streak == 4  # incremented on auto-approve
