"""Join-by-family-code role assignment.

Joining an existing family via join code (password OR Google OAuth) must
NOT grant parent powers: the requested role is honored only for child/teen
(defaulting to CHILD; a requested 'parent' is demoted to CHILD), and the
account starts PENDING parental approval. Founding a new family always
creates a PARENT regardless of any role in the payload.
"""
import pytest
from sqlalchemy import select

from app.models.family import Family, generate_join_code
from app.models.user import User, UserRole


async def _join_code_for(db_session, test_family) -> str:
    fam = (await db_session.execute(
        select(Family).where(Family.id == test_family.id)
    )).scalar_one()
    if not fam.join_code:
        fam.join_code = generate_join_code()
        await db_session.commit()
        await db_session.refresh(fam)
    return fam.join_code


@pytest.mark.asyncio
async def test_join_by_code_defaults_to_child(client, db_session, test_family):
    code = await _join_code_for(db_session, test_family)
    r = await client.post("/api/auth/register-family", json={
        "email": "kid-default@test.com",
        "name": "Kid Default",
        "password": "password123",
        "family_code": code,
    })
    assert r.status_code in (200, 201)
    assert r.json()["user"]["role"] == "child"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["child", "teen"])
async def test_join_by_code_honors_requested_role(client, db_session, test_family, role):
    code = await _join_code_for(db_session, test_family)
    r = await client.post("/api/auth/register-family", json={
        "email": f"joiner-{role}@test.com",
        "name": f"Joiner {role}",
        "password": "password123",
        "family_code": code,
        "role": role,
    })
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["user"]["role"] == role
    user = (await db_session.execute(
        select(User).where(User.email == f"joiner-{role}@test.com")
    )).scalar_one()
    assert user.role == UserRole(role)
    assert str(user.family_id) == str(test_family.id)


@pytest.mark.asyncio
async def test_join_by_code_never_mints_parent(client, db_session, test_family):
    """SECURITY/COMPLIANCE (2026-07-07): requesting role=parent via join code
    is demoted to CHILD — PARENT only via invitation or family creation."""
    code = await _join_code_for(db_session, test_family)
    r = await client.post("/api/auth/register-family", json={
        "email": "joiner-parent@test.com",
        "name": "Joiner parent",
        "password": "password123",
        "family_code": code,
        "role": "parent",
    })
    assert r.status_code in (200, 201)
    assert r.json()["user"]["role"] == "child"
    user = (await db_session.execute(
        select(User).where(User.email == "joiner-parent@test.com")
    )).scalar_one()
    assert user.role == UserRole.CHILD


@pytest.mark.asyncio
async def test_founding_family_is_always_parent(client):
    r = await client.post("/api/auth/register-family", json={
        "email": "founder-role@test.com",
        "name": "Founder",
        "password": "password123",
        "family_name": "Role Test Family",
        "role": "child",  # must be ignored when creating a new family
        "accept_terms": True,
    })
    assert r.status_code in (200, 201)
    assert r.json()["user"]["role"] == "parent"


@pytest.mark.asyncio
async def test_google_join_existing_family_is_not_parent(db_session, test_family):
    """A new Google user landing in an EXISTING family (join_code or a
    client-supplied family_id) must default to CHILD — family_id is not a
    secret, so it must not mint parents. Both self-signup paths also start
    PENDING parental approval: the account is created but NO tokens are
    issued (the service raises 403 with the wait-for-parent message)."""
    from app.core.exceptions import ForbiddenException
    from app.models.user import APPROVAL_PENDING
    from app.services.google_oauth_service import GoogleOAuthService

    code = await _join_code_for(db_session, test_family)
    for kwargs, email in [
        ({"join_code": code}, "g-kid-code@test.com"),
        ({"family_id": str(test_family.id)}, "g-kid-id@test.com"),
    ]:
        with pytest.raises(ForbiddenException):
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                {
                    "google_id": f"gid-{email}",
                    "email": email,
                    "name": "Google Kid",
                    "email_verified": True,
                },
                **kwargs,
            )
        user = (await db_session.execute(
            select(User).where(User.email == email)
        )).scalar_one()
        assert user.role == UserRole.CHILD
        assert str(user.family_id) == str(test_family.id)
        assert user.approval_status == APPROVAL_PENDING
        assert user.approved_at is None


@pytest.mark.asyncio
async def test_google_new_family_founder_is_parent(db_session):
    from app.services.google_oauth_service import GoogleOAuthService

    user, access_token, _, is_new = await GoogleOAuthService.authenticate_or_create_user(
        db_session,
        {
            "google_id": "gid-founder",
            "email": "g-founder@test.com",
            "name": "Google Founder",
            "email_verified": True,
        },
        accept_terms=True,  # founding a family requires consent
    )
    assert is_new is True
    assert user.role == UserRole.PARENT
    assert access_token


@pytest.mark.asyncio
async def test_join_by_code_rejects_invalid_role(client, db_session, test_family):
    code = await _join_code_for(db_session, test_family)
    r = await client.post("/api/auth/register-family", json={
        "email": "bad-role@test.com",
        "name": "Bad Role",
        "password": "password123",
        "family_code": code,
        "role": "admin",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_google_join_by_code_caps_role_at_teen(db_session, test_family):
    """SECURITY/COMPLIANCE (2026-07-07): join codes are shared with kids, so
    the Google join-by-code path honors child/teen but DEMOTES a requested
    'parent' to CHILD — same policy as /api/auth/register-family."""
    from app.core.exceptions import ForbiddenException
    from app.services.google_oauth_service import GoogleOAuthService

    code = await _join_code_for(db_session, test_family)
    for requested, expected, email in [
        ("teen", UserRole.TEEN, "g-teen@test.com"),
        ("child", UserRole.CHILD, "g-child@test.com"),
        ("parent", UserRole.CHILD, "g-par@test.com"),  # demoted
    ]:
        with pytest.raises(ForbiddenException):  # pending → no tokens
            await GoogleOAuthService.authenticate_or_create_user(
                db_session,
                {"google_id": f"gid-{email}", "email": email, "name": "G", "email_verified": True},
                join_code=code,
                role=requested,
            )
        user = (await db_session.execute(
            select(User).where(User.email == email)
        )).scalar_one()
        assert user.role == expected


@pytest.mark.asyncio
async def test_google_family_id_ignores_requested_parent_role(db_session, test_family):
    """SECURITY: family_id is not a secret, so role='parent' on the family_id
    path must NOT mint a parent — it is forced to CHILD."""
    from app.core.exceptions import ForbiddenException
    from app.services.google_oauth_service import GoogleOAuthService

    with pytest.raises(ForbiddenException):  # pending → no tokens
        await GoogleOAuthService.authenticate_or_create_user(
            db_session,
            {"google_id": "gid-escalate", "email": "g-escalate@test.com", "name": "G", "email_verified": True},
            family_id=str(test_family.id),
            role="parent",
        )
    user = (await db_session.execute(
        select(User).where(User.email == "g-escalate@test.com")
    )).scalar_one()
    assert user.role == UserRole.CHILD
    assert str(user.family_id) == str(test_family.id)


@pytest.mark.asyncio
async def test_google_route_rejects_invalid_role(client):
    """Pydantic validates role before Google verification, so no token mock
    is needed to prove the enum is enforced at the route boundary."""
    r = await client.post("/api/oauth/google", json={
        "token": "x", "join_code": "ABC123", "role": "admin",
    })
    assert r.status_code == 422
