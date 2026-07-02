"""Join-by-family-code role assignment.

Joining an existing family via join code must NOT grant parent powers by
default: the requested role (child/teen/parent) is honored, defaulting to
CHILD. Founding a new family always creates a PARENT regardless of any
role in the payload.
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
@pytest.mark.parametrize("role", ["child", "teen", "parent"])
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
async def test_founding_family_is_always_parent(client):
    r = await client.post("/api/auth/register-family", json={
        "email": "founder-role@test.com",
        "name": "Founder",
        "password": "password123",
        "family_name": "Role Test Family",
        "role": "child",  # must be ignored when creating a new family
    })
    assert r.status_code in (200, 201)
    assert r.json()["user"]["role"] == "parent"


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
