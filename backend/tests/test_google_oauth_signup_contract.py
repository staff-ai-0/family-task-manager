"""Google OAuth signup contract: plan member cap + structured error codes.

Regression tests for two launch-P0 review findings:

1. MAJOR — OAuth self-signup into an existing family (join_code or
   family_id) must enforce the same family_member plan cap as the password
   register path (the join branch of POST /api/auth/register-family) and
   the invitation path. Same error shape too: 403 with a plain-string
   bilingual ``detail``.

2. MINOR — native clients (GOOGLE_CLIENT_IDS multi-aud) need
   machine-readable error codes from POST /api/oauth/google:
   - 400 ``error="consent_required"`` when a new-family signup omits
     accept_terms (bilingual message/message_es, mirroring the
     email_not_verified field shape) — so the app can render a consent
     screen and retry;
   - 403 ``error="approval_pending"`` for join self-signups pending
     parental approval (account created, NO tokens).
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.family import Family, generate_join_code
from app.models.user import APPROVAL_PENDING, User, UserRole
from app.services.google_oauth_service import (
    GoogleOAuthService,
    OAuthApprovalPendingError,
    OAuthConsentRequiredError,
)


FREE_PLAN_MEMBER_CAP = 4  # DEFAULT_FREE_LIMITS["max_family_members"]


def _ginfo(email: str, name: str = "G User") -> dict:
    return {
        "google_id": f"gid-{email}",
        "email": email,
        "name": name,
        "email_verified": True,
    }


def _mock_verify(monkeypatch, email: str, name: str = "G User") -> None:
    async def fake_verify(token):
        return _ginfo(email, name)

    monkeypatch.setattr(
        GoogleOAuthService, "verify_google_token", staticmethod(fake_verify)
    )


async def _join_code_for(db_session, family) -> str:
    fam = (await db_session.execute(
        select(Family).where(Family.id == family.id)
    )).scalar_one()
    if not fam.join_code:
        fam.join_code = generate_join_code()
        await db_session.commit()
        await db_session.refresh(fam)
    return fam.join_code


async def _fill_family_to_cap(db_session, family, cap: int = FREE_PLAN_MEMBER_CAP):
    """Add active CHILD members until the family has exactly `cap` members."""
    existing = (await db_session.execute(
        select(User).where(
            User.family_id == family.id,
            User.is_active == True,  # noqa: E712
        )
    )).scalars().all()
    for i in range(cap - len(existing)):
        db_session.add(User(
            email=f"cap-filler-{i}@test.com",
            password_hash=None,
            name=f"Cap Filler {i}",
            role=UserRole.CHILD,
            family_id=family.id,
            points=0,
            email_verified=True,
        ))
    await db_session.commit()


async def _user_by_email(db_session, email: str):
    return (await db_session.execute(
        select(User).where(User.email == email)
    )).scalar_one_or_none()


class TestOAuthJoinMemberCap:
    """MAJOR: OAuth join must not bypass the family_member plan limit."""

    @pytest.mark.asyncio
    async def test_join_code_at_cap_is_blocked(
        self, db_session, test_family, test_parent_user
    ):
        code = await _join_code_for(db_session, test_family)
        await _fill_family_to_cap(db_session, test_family)

        with pytest.raises(HTTPException) as ei:
            await GoogleOAuthService.authenticate_or_create_user(
                db_session, _ginfo("capped-kid@test.com"), join_code=code
            )
        assert ei.value.status_code == 403
        # Same copy as the password join branch (auth.py), bilingual
        assert "member limit" in ei.value.detail
        assert "límite de miembros" in ei.value.detail
        # No account was created
        assert await _user_by_email(db_session, "capped-kid@test.com") is None

    @pytest.mark.asyncio
    async def test_family_id_at_cap_is_blocked(
        self, db_session, test_family, test_parent_user
    ):
        """family_id is the other self-signup path into an existing family;
        it must be capped identically (it's not even a secret)."""
        await _fill_family_to_cap(db_session, test_family)

        with pytest.raises(HTTPException) as ei:
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                _ginfo("capped-kid-id@test.com"),
                family_id=str(test_family.id),
            )
        assert ei.value.status_code == 403
        assert "member limit" in ei.value.detail
        assert await _user_by_email(db_session, "capped-kid-id@test.com") is None

    @pytest.mark.asyncio
    async def test_route_join_at_cap_matches_password_path_shape(
        self, client, db_session, test_family, test_parent_user, monkeypatch
    ):
        """Route-level equivalence: the OAuth join and the password join
        return the same shape at cap — 403 with a plain-string detail."""
        code = await _join_code_for(db_session, test_family)
        await _fill_family_to_cap(db_session, test_family)

        _mock_verify(monkeypatch, "capped-route@test.com")
        r_oauth = await client.post("/api/oauth/google", json={
            "token": "fake", "join_code": code,
        })
        r_pw = await client.post("/api/auth/register-family", json={
            "email": "capped-pw@test.com",
            "name": "Capped PW",
            "password": "password123",
            "family_code": code,
        })

        assert r_oauth.status_code == 403, r_oauth.text
        assert r_pw.status_code == 403, r_pw.text
        oauth_detail = r_oauth.json()["detail"]
        pw_detail = r_pw.json()["detail"]
        assert isinstance(oauth_detail, str)
        assert isinstance(pw_detail, str)
        assert "member limit" in oauth_detail
        # Neither account was created
        assert await _user_by_email(db_session, "capped-route@test.com") is None
        assert await _user_by_email(db_session, "capped-pw@test.com") is None

    @pytest.mark.asyncio
    async def test_join_below_cap_still_works(
        self, client, db_session, test_family, test_parent_user, monkeypatch
    ):
        """Guard: the cap check must not block normal joins — below the cap
        the signup proceeds to the usual PENDING outcome (account created)."""
        code = await _join_code_for(db_session, test_family)

        _mock_verify(monkeypatch, "below-cap@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake", "join_code": code,
        })
        assert r.status_code == 403
        assert r.json()["error"] == "approval_pending"  # NOT the limit error
        user = await _user_by_email(db_session, "below-cap@test.com")
        assert user is not None
        assert user.approval_status == APPROVAL_PENDING


class TestOAuthStructuredErrorCodes:
    """MINOR: machine-readable consent_required / approval_pending codes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload_extra", [
        {},                        # accept_terms omitted (native clients today)
        {"accept_terms": False},   # explicit false
    ])
    async def test_new_family_without_consent_returns_consent_required(
        self, client, db_session, monkeypatch, payload_extra
    ):
        _mock_verify(monkeypatch, "no-consent@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake", **payload_extra,
        })
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["error"] == "consent_required"
        # Bilingual copy, email_not_verified field shape
        assert "Terms" in body["message"]
        assert "Términos" in body["message_es"]
        assert body["status_code"] == 400
        assert "access_token" not in body
        # No account was created — retry with accept_terms=true must work
        assert await _user_by_email(db_session, "no-consent@test.com") is None

    @pytest.mark.asyncio
    async def test_new_family_with_consent_returns_tokens(
        self, client, db_session, monkeypatch
    ):
        """The consent screen retry path: same request + accept_terms=true
        succeeds with tokens (founder PARENT)."""
        _mock_verify(monkeypatch, "consented@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake", "accept_terms": True,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["access_token"]
        assert body["refresh_token"]
        assert body["user"]["role"] == "parent"
        user = await _user_by_email(db_session, "consented@test.com")
        assert user is not None
        assert user.consented_at is not None

    @pytest.mark.asyncio
    async def test_join_signup_returns_approval_pending_code(
        self, client, db_session, test_family, test_parent_user, monkeypatch
    ):
        code = await _join_code_for(db_session, test_family)
        _mock_verify(monkeypatch, "pending-code@test.com")
        r = await client.post("/api/oauth/google", json={
            "token": "fake", "join_code": code,
        })
        assert r.status_code == 403, r.text
        body = r.json()
        assert body["error"] == "approval_pending"
        assert "pending" in body["message"].lower()
        assert "pendiente" in body["message_es"].lower()
        assert body["status_code"] == 403
        assert "access_token" not in body
        assert "refresh_token" not in body

    @pytest.mark.asyncio
    async def test_existing_pending_user_retry_returns_approval_pending_code(
        self, client, db_session, test_family, test_parent_user, monkeypatch
    ):
        """Retrying 'Sign in with Google' while pending hits the
        existing-user branch and must carry the same explicit code."""
        code = await _join_code_for(db_session, test_family)
        _mock_verify(monkeypatch, "pending-retry@test.com")
        r1 = await client.post("/api/oauth/google", json={
            "token": "fake", "join_code": code,
        })
        assert r1.status_code == 403
        r2 = await client.post("/api/oauth/google", json={"token": "fake"})
        assert r2.status_code == 403
        assert r2.json()["error"] == "approval_pending"

    def test_structured_errors_degrade_to_legacy_exception_types(self):
        """Back-compat guard: uncaught instances must still hit the global
        400 validation_error / 403 forbidden handlers (and keep existing
        pytest.raises(ValidationException/ForbiddenException) tests green)."""
        from app.core.exceptions import ForbiddenException, ValidationException

        assert issubclass(OAuthConsentRequiredError, ValidationException)
        assert issubclass(OAuthApprovalPendingError, ForbiddenException)
        consent = OAuthConsentRequiredError()
        assert consent.code == "consent_required"
        assert "Términos" in str(consent) and "Terms" in str(consent)
        pending = OAuthApprovalPendingError("es")
        assert pending.code == "approval_pending"
        assert pending.message_en and pending.message_es
        assert "pendiente" in str(pending)
