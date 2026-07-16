"""Gig-claim comment threads: parent ↔ kid conversation about a completed gig.

Visibility: family parents + the claim owner. Comments notify the other side
(parent comment → kid; kid comment → parents).
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.gig import GigClaim, GigClaimStatus, GigOffering
from app.models.notification import Notification, NotificationType


@pytest_asyncio.fixture
async def completed_claim(db_session, test_family, test_child_user):
    offering = GigOffering(
        family_id=test_family.id,
        title="Leer libro de Karma",
        points=50,
        difficulty=1,
    )
    db_session.add(offering)
    await db_session.flush()
    claim = GigClaim(
        gig_id=offering.id,
        family_id=test_family.id,
        claimed_by=test_child_user.id,
        status=GigClaimStatus.COMPLETED,
        proof_text="Leí los 3 primeros capítulos",
    )
    db_session.add(claim)
    await db_session.commit()
    await db_session.refresh(claim)
    return claim


async def _login(client: AsyncClient, email: str) -> dict:
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": "password123"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.mark.asyncio
async def test_parent_comment_visible_to_kid_and_notifies(
    client: AsyncClient, db_session, test_parent_user, test_child_user, completed_claim
):
    parent_h = await _login(client, test_parent_user.email)
    r = await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "¿Qué fue lo que más te gustó del libro?"},
        headers=parent_h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["body"].startswith("¿Qué fue")
    assert r.json()["author_name"] == test_parent_user.name

    kid_h = await _login(client, test_child_user.email)
    r = await client.get(
        f"/api/gigs/claims/{completed_claim.id}/comments", headers=kid_h
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 1
    assert items[0]["body"] == "¿Qué fue lo que más te gustó del libro?"

    notif = (
        await db_session.execute(
            select(Notification).where(
                Notification.type == NotificationType.GIG_COMMENT,
                Notification.user_id == test_child_user.id,
            )
        )
    ).scalars().all()
    assert len(notif) == 1


@pytest.mark.asyncio
async def test_kid_comment_notifies_parents(
    client: AsyncClient, db_session, test_parent_user, test_child_user, completed_claim
):
    kid_h = await _login(client, test_child_user.email)
    r = await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "El capítulo 2, cuando Karma encuentra el mapa"},
        headers=kid_h,
    )
    assert r.status_code == 201, r.text

    parent_h = await _login(client, test_parent_user.email)
    r = await client.get(
        f"/api/gigs/claims/{completed_claim.id}/comments", headers=parent_h
    )
    assert r.status_code == 200
    assert len(r.json()) == 1

    notif = (
        await db_session.execute(
            select(Notification).where(
                Notification.type == NotificationType.GIG_COMMENT,
                Notification.user_id == test_parent_user.id,
            )
        )
    ).scalars().all()
    assert len(notif) == 1


@pytest.mark.asyncio
async def test_non_owner_kid_blocked(
    client: AsyncClient, test_teen_user, completed_claim
):
    teen_h = await _login(client, test_teen_user.email)
    r = await client.get(
        f"/api/gigs/claims/{completed_claim.id}/comments", headers=teen_h
    )
    assert r.status_code == 403
    r = await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "yo también quiero opinar"},
        headers=teen_h,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_other_family_blocked(
    client: AsyncClient, db_session, sample_family, completed_claim
):
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    stranger = User(
        email="stranger-gig-comments@test.com",
        name="Stranger",
        password_hash=get_password_hash("password123"),
        role=UserRole.PARENT,
        family_id=sample_family.id,
        is_active=True,
    )
    db_session.add(stranger)
    await db_session.commit()

    h = await _login(client, stranger.email)
    r = await client.get(
        f"/api/gigs/claims/{completed_claim.id}/comments", headers=h
    )
    assert r.status_code == 404
    r = await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "espía"},
        headers=h,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_family_claims_list_includes_comment_count(
    client: AsyncClient, test_parent_user, completed_claim
):
    parent_h = await _login(client, test_parent_user.email)
    await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "uno"},
        headers=parent_h,
    )
    await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "dos"},
        headers=parent_h,
    )
    r = await client.get("/api/gigs/claims/family", headers=parent_h)
    assert r.status_code == 200
    row = next(c for c in r.json() if c["id"] == str(completed_claim.id))
    assert row["comment_count"] == 2


@pytest.mark.asyncio
async def test_my_claims_list_includes_comment_count(
    client: AsyncClient, test_parent_user, test_child_user, completed_claim
):
    parent_h = await _login(client, test_parent_user.email)
    await client.post(
        f"/api/gigs/claims/{completed_claim.id}/comments",
        json={"body": "bravo"},
        headers=parent_h,
    )
    kid_h = await _login(client, test_child_user.email)
    r = await client.get("/api/gigs/claims/my", headers=kid_h)
    assert r.status_code == 200
    row = next(c for c in r.json() if c["id"] == str(completed_claim.id))
    assert row["comment_count"] == 1
