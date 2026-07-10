"""Parent moderation of the family chat: edit + delete any message.

Parents can edit or delete ANY message in their family's chat (moderation).
Non-parents get 403 — this is a moderation right, not self-service editing.
Multi-tenant: a parent can never touch another family's messages.
"""

import pytest
from sqlalchemy import select

from app.models.family_chat import FamilyChatMessage


async def _login(client, email):
    r = await client.post("/api/auth/login", json={
        "email": email, "password": "password123",
    })
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _post_message(client, headers, body="hola familia"):
    r = await client.post("/api/chat/", json={"body": body}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.mark.asyncio
async def test_parent_edits_any_message(
    client, db_session, test_family, test_parent_user, test_child_user
):
    child_h = await _login(client, test_child_user.email)
    parent_h = await _login(client, test_parent_user.email)
    msg = await _post_message(client, child_h, "groseria del nino")

    r = await client.put(
        f"/api/chat/{msg['id']}",
        json={"body": "mensaje moderado"},
        headers=parent_h,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["body"] == "mensaje moderado"
    assert out["edited_at"] is not None

    row = (await db_session.execute(
        select(FamilyChatMessage).where(FamilyChatMessage.id == msg["id"])
    )).scalar_one()
    assert row.body == "mensaje moderado"
    assert row.edited_at is not None


@pytest.mark.asyncio
async def test_parent_deletes_any_message(
    client, db_session, test_family, test_parent_user, test_child_user
):
    child_h = await _login(client, test_child_user.email)
    parent_h = await _login(client, test_parent_user.email)
    msg = await _post_message(client, child_h)

    r = await client.delete(f"/api/chat/{msg['id']}", headers=parent_h)
    assert r.status_code == 204, r.text

    row = (await db_session.execute(
        select(FamilyChatMessage).where(FamilyChatMessage.id == msg["id"])
    )).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_child_cannot_edit_or_delete(
    client, db_session, test_family, test_parent_user, test_child_user
):
    child_h = await _login(client, test_child_user.email)
    own = await _post_message(client, child_h, "mio")

    r = await client.put(
        f"/api/chat/{own['id']}", json={"body": "hackeado"}, headers=child_h
    )
    assert r.status_code == 403

    r = await client.delete(f"/api/chat/{own['id']}", headers=child_h)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_parent_cannot_touch_other_family_messages(
    client, db_session, test_family, test_parent_user, test_child_user
):
    from app.models.family import Family
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    other_family = Family(name="Other Fam")
    db_session.add(other_family)
    await db_session.commit()
    await db_session.refresh(other_family)
    other_parent = User(
        email="otherparent@test.com",
        password_hash=get_password_hash("password123"),
        name="Other Parent", role=UserRole.PARENT,
        family_id=other_family.id, email_verified=True, points=0,
    )
    db_session.add(other_parent)
    await db_session.commit()

    parent_h = await _login(client, test_parent_user.email)
    msg = await _post_message(client, parent_h, "nuestro chat")

    other_h = await _login(client, "otherparent@test.com")
    r = await client.put(
        f"/api/chat/{msg['id']}", json={"body": "intruso"}, headers=other_h
    )
    assert r.status_code == 404

    r = await client.delete(f"/api/chat/{msg['id']}", headers=other_h)
    assert r.status_code == 404
