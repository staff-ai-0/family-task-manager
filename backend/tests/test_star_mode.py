"""Star Mode (P2) tests — per-kid young-kid display toggle over POINTS.

Star Mode is pure presentation (render points as stars, hide peso amounts). The
backend surface is: PUT /api/users/{id}/star-mode (parent, CHILD/TEEN only),
star_mode on UserResponse (/auth/me), and star_mode on the kiosk pin-view. No
currency, no balance change, family-scoped.

Run: podman exec -e PYTHONPATH=/app family_app_backend \
     pytest tests/test_star_mode.py -v --no-cov
"""
import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.kiosk_device import KioskDevice
from app.models.user import User, UserRole
from app.services.member_prefs_service import MemberPrefsService


async def _login(client, email, pw="password123"):
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── toggle + persistence ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_persists_and_does_not_touch_balances(
    client, db_session, test_parent_user, test_child_user
):
    before_points = test_child_user.points
    before_cash = test_child_user.cash_cents
    h = await _login(client, "parent@test.com")

    r = await client.put(
        f"/api/users/{test_child_user.id}/star-mode", json={"enabled": True}, headers=h
    )
    assert r.status_code == 200
    assert r.json()["star_mode"] is True

    await db_session.refresh(test_child_user)
    assert test_child_user.star_mode is True
    # Pure presentation — the points/cash balances are untouched.
    assert test_child_user.points == before_points
    assert test_child_user.cash_cents == before_cash

    # Toggling off persists too.
    r2 = await client.put(
        f"/api/users/{test_child_user.id}/star-mode", json={"enabled": False}, headers=h
    )
    assert r2.status_code == 200
    assert r2.json()["star_mode"] is False
    await db_session.refresh(test_child_user)
    assert test_child_user.star_mode is False


@pytest.mark.asyncio
async def test_star_mode_defaults_false_and_shows_in_me(
    client, test_parent_user, test_child_user
):
    ph = await _login(client, "parent@test.com")
    ch = await _login(client, "child@test.com")

    me = await client.get("/api/auth/me", headers=ch)
    assert me.status_code == 200
    assert me.json()["star_mode"] is False  # default off

    await client.put(
        f"/api/users/{test_child_user.id}/star-mode", json={"enabled": True}, headers=ph
    )
    me2 = await client.get("/api/auth/me", headers=ch)
    assert me2.json()["star_mode"] is True


# ── gating + isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_enable_on_a_parent(client, test_parent_user):
    h = await _login(client, "parent@test.com")
    r = await client.put(
        f"/api/users/{test_parent_user.id}/star-mode", json={"enabled": True}, headers=h
    )
    assert r.status_code == 400  # ValidationException: CHILD/TEEN only


@pytest.mark.asyncio
async def test_kid_cannot_toggle_star_mode(client, test_child_user, test_teen_user):
    # A kid is not a parent → require_parent_role blocks it.
    h = await _login(client, "child@test.com")
    r = await client.put(
        f"/api/users/{test_teen_user.id}/star-mode", json={"enabled": True}, headers=h
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cross_family_toggle_forbidden(client, db_session, test_child_user):
    fam_b = Family(name="Other")
    db_session.add(fam_b)
    await db_session.commit()
    await db_session.refresh(fam_b)
    parent_b = User(
        email="pb-star@test.com", password_hash=get_password_hash("password123"),
        name="PB", role=UserRole.PARENT, family_id=fam_b.id, email_verified=True,
    )
    db_session.add(parent_b)
    await db_session.commit()

    h = await _login(client, "pb-star@test.com")
    r = await client.put(
        f"/api/users/{test_child_user.id}/star-mode", json={"enabled": True}, headers=h
    )
    assert r.status_code == 403  # get_family_user: not in same family


# ── kiosk pin-view renders star_mode ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_kiosk_pin_view_reports_star_mode(
    client, db_session, test_family, test_parent_user, test_child_user
):
    device = KioskDevice(
        family_id=test_family.id, name="Hall", token="kstar" * 8  # 40 chars
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)
    await MemberPrefsService.update_member_prefs(
        test_family.id, test_child_user.id, pin="1234"
    )

    # Default: star_mode off → kiosk reports false.
    r0 = await client.post(
        "/api/kiosk/pin-view",
        json={"token": device.token, "user_id": str(test_child_user.id), "pin": "1234"},
    )
    assert r0.status_code == 200
    body0 = r0.json()
    assert body0["star_mode"] is False
    assert "cash_cents" in body0 and "points" in body0  # both still present in payload

    # Enable star mode → kiosk now reports true (frontend swaps to stars / hides cash).
    ph = await _login(client, "parent@test.com")
    await client.put(
        f"/api/users/{test_child_user.id}/star-mode", json={"enabled": True}, headers=ph
    )
    r1 = await client.post(
        "/api/kiosk/pin-view",
        json={"token": device.token, "user_id": str(test_child_user.id), "pin": "1234"},
    )
    assert r1.status_code == 200
    assert r1.json()["star_mode"] is True
