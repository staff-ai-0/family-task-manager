"""Family timezone exposure + capture.

The Astro SSR container runs in UTC, so pages must render timestamps in the
family's timezone. That requires two things this file guards:

1. /api/auth/me denormalizes the family's IANA timezone (same pattern as
   enabled_modules) so every SSR page can format timestamps correctly.
2. OAuth signups that CREATE a family apply the browser-supplied timezone
   (the password path already did; the OAuth path used to leave every
   Google-founded family stuck on UTC).
"""

import pytest
from sqlalchemy import select

from app.models.family import Family
from app.models.user import User
from app.services.google_oauth_service import GoogleOAuthService


def _mock_verify(monkeypatch, email: str, name: str = "TZ User") -> None:
    async def fake_verify(token):
        return {
            "google_id": f"gid-{email}",
            "email": email,
            "name": name,
            "email_verified": True,
        }

    monkeypatch.setattr(
        GoogleOAuthService, "verify_google_token", staticmethod(fake_verify)
    )


async def _family_of(db_session, email: str) -> Family:
    user = (await db_session.execute(
        select(User).where(User.email == email)
    )).scalar_one()
    return (await db_session.execute(
        select(Family).where(Family.id == user.family_id)
    )).scalar_one()


class TestAuthMeTimezone:
    @pytest.mark.asyncio
    async def test_me_returns_family_timezone(
        self, client, db_session, test_family, test_parent_user
    ):
        test_family.timezone = "America/Mexico_City"
        await db_session.commit()

        login = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login.json()["access_token"]
        r = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        assert r.json()["timezone"] == "America/Mexico_City"

    @pytest.mark.asyncio
    async def test_me_timezone_defaults_to_utc(
        self, client, test_family, test_parent_user
    ):
        login = await client.post(
            "/api/auth/login",
            json={"email": test_parent_user.email, "password": "password123"},
        )
        token = login.json()["access_token"]
        r = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 200
        assert r.json()["timezone"] == "UTC"


class TestOAuthSignupTimezone:
    @pytest.mark.asyncio
    async def test_new_family_applies_browser_timezone(
        self, client, db_session, monkeypatch
    ):
        _mock_verify(monkeypatch, "tz-capture@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake",
            "accept_terms": True,
            "timezone": "America/Mexico_City",
        })
        assert r.status_code == 200, r.text
        family = await _family_of(db_session, "tz-capture@test.com")
        assert family.timezone == "America/Mexico_City"

    @pytest.mark.asyncio
    async def test_new_family_invalid_timezone_falls_back_to_utc(
        self, client, db_session, monkeypatch
    ):
        _mock_verify(monkeypatch, "tz-bogus@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake",
            "accept_terms": True,
            "timezone": "Not/AZone",
        })
        assert r.status_code == 200, r.text
        family = await _family_of(db_session, "tz-bogus@test.com")
        assert family.timezone == "UTC"

    @pytest.mark.asyncio
    async def test_new_family_without_timezone_defaults_to_utc(
        self, client, db_session, monkeypatch
    ):
        _mock_verify(monkeypatch, "tz-none@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake",
            "accept_terms": True,
        })
        assert r.status_code == 200, r.text
        family = await _family_of(db_session, "tz-none@test.com")
        assert family.timezone == "UTC"
