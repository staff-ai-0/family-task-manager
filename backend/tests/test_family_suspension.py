"""families.is_active must actually lock a family out.

Before this change is_active was enforced in exactly two places (join-code
lookup and registration), so a "suspended" family kept using the entire app.
"""

import pytest

from app.core.exceptions import UnauthorizedException
from app.core.security import create_refresh_token
from app.services.google_oauth_service import GoogleOAuthService


@pytest.mark.asyncio
async def test_suspended_family_cannot_log_in(
    client, db_session, test_family, test_parent_user
):
    test_family.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "password123"},
    )
    assert resp.status_code == 401
    # UnauthorizedException goes through unauthorized_handler, which puts the
    # message under "message" (not "detail"). Pinned so a refactor can't
    # silently collapse this back to the generic auth-failure message.
    assert resp.json()["message"] == "Family suspended"


@pytest.mark.asyncio
async def test_suspended_family_wrong_password_leaks_nothing(
    client, db_session, test_family, test_parent_user
):
    """A wrong password against a suspended family's account must still get
    the generic "Invalid email or password" — never "Family suspended".
    Otherwise the suspension check becomes an account-enumeration oracle:
    an attacker could distinguish "wrong password" from "family suspended"
    without ever having a valid password. Password verification must run
    before the suspension check is ever consulted.
    """
    test_family.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/auth/login",
        json={"email": "parent@test.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["message"] == "Invalid email or password"


@pytest.mark.asyncio
async def test_existing_token_stops_working_once_family_suspended(
    client, db_session, auth_headers, test_family
):
    ok = await client.get("/api/auth/me", headers=auth_headers)
    assert ok.status_code == 200

    test_family.is_active = False
    await db_session.commit()

    blocked = await client.get("/api/auth/me", headers=auth_headers)
    assert blocked.status_code == 401
    # get_current_user raises a plain HTTPException, which FastAPI serializes
    # under "detail". Pinned for the same reason as the login-side message
    # above — nothing else in this suite checks the actual wording.
    assert blocked.json()["detail"] == "Family suspended"


@pytest.mark.asyncio
async def test_suspended_request_does_not_stamp_last_seen_at(
    client, db_session, auth_headers, test_family, test_parent_user
):
    """The suspension check sits before `await _touch_last_seen(...)` in
    get_current_user on purpose: a rejected request must not look like
    activity. Confirm that ordering holds — a fresh user has never been
    touched, and a suspended-and-blocked request must leave it that way.
    """
    assert test_parent_user.last_seen_at is None

    test_family.is_active = False
    await db_session.commit()

    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 401

    await db_session.refresh(test_parent_user)
    assert test_parent_user.last_seen_at is None


@pytest.mark.asyncio
async def test_unsuspending_restores_access(
    client, db_session, auth_headers, test_family
):
    test_family.is_active = False
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 401

    test_family.is_active = True
    await db_session.commit()
    assert (await client.get("/api/auth/me", headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_suspended_family_cannot_google_sign_in(
    db_session, test_family, test_parent_user
):
    """Google sign-in is the login door most users actually use. A member of
    a suspended family must be rejected here too, not just at password login
    and get_current_user — otherwise they'd complete OAuth, get valid
    cookies, and land on a dashboard where every call 401s.
    """
    test_family.is_active = False
    await db_session.commit()

    google_user_info = {
        "google_id": "google-suspended-test-id",
        "email": test_parent_user.email,
        "email_verified": True,
        "name": test_parent_user.name,
    }

    with pytest.raises(UnauthorizedException) as exc_info:
        await GoogleOAuthService.authenticate_or_create_user(
            db_session, google_user_info
        )
    # Same exact message as the password-login and get_current_user paths so
    # the frontend can key on one string.
    assert str(exc_info.value) == "Family suspended"


@pytest.mark.asyncio
async def test_suspended_family_cannot_refresh_tokens(
    client, db_session, test_family, test_parent_user
):
    """A suspended family's member must not be able to keep minting fresh
    (if useless) access tokens via /api/auth/refresh — otherwise the
    frontend's transparent-refresh middleware keeps succeeding and the user
    never gets bounced to /login where they'd see the suspension message.
    """
    refresh = create_refresh_token(
        str(test_parent_user.id), version=test_parent_user.token_version
    )

    test_family.is_active = False
    await db_session.commit()

    resp = await client.post(
        "/api/auth/refresh",
        headers={"Authorization": f"Bearer {refresh}"},
    )
    assert resp.status_code == 401, resp.text
