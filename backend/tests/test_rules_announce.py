"""Rules announcement: POST /api/rules/announce + auto-announce on version bump."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.notification import Notification
from app.models.rules_acceptance import RulesAcceptance
from app.models.user import User, UserRole
from app.services.rules_service import RulesService


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _eb(db, family, on=True):
    family.early_bird_enabled = on
    await db.commit()


async def _rules_notes(db, family_id=None):
    q = select(Notification).where(Notification.type == "rules_update")
    if family_id is not None:
        q = q.where(Notification.family_id == family_id)
    return list((await db.execute(q)).scalars().all())


async def test_announce_one_per_active_member(
    client, db_session, test_family, test_parent_user, test_teen_user, test_child_user, auth_headers
):
    await _eb(db_session, test_family)
    test_child_user.preferred_lang = "es"
    test_teen_user.preferred_lang = "en"
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    db_session.add(User(email="o@test.com", password_hash=get_password_hash("x"), name="O",
                        role=UserRole.PARENT, family_id=other.id, email_verified=True))
    db_session.add(User(email="gone@test.com", password_hash=get_password_hash("x"), name="Gone",
                        role=UserRole.CHILD, family_id=test_family.id, is_active=False))
    await db_session.commit()

    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"sent": 3}
    notes = await _rules_notes(db_session)
    assert len(notes) == 3
    assert {n.user_id for n in notes} == {test_parent_user.id, test_teen_user.id, test_child_user.id}
    assert all(n.family_id == test_family.id for n in notes)
    assert all(n.link == "/dashboard?rules=1" for n in notes)
    by_user = {n.user_id: n for n in notes}
    assert by_user[test_child_user.id].title == "Nuevas reglas de tareas"
    assert by_user[test_teen_user.id].title == "New chore rules"
    assert by_user[test_teen_user.id].body == "Read them and accept so it's on record."


async def test_second_announce_within_hour_429_then_allowed(
    client, db_session, test_family, test_parent_user, auth_headers
):
    await _eb(db_session, test_family)
    assert (await client.post("/api/rules/announce", headers=auth_headers)).status_code == 200
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 429 and r.json()["code"] == "announce_too_soon"
    await db_session.execute(
        update(Notification).where(Notification.type == "rules_update")
        .values(created_at=datetime.now(timezone.utc) - timedelta(hours=1, minutes=1))
    )
    await db_session.commit()
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"sent": 1}


async def test_eb_off_409(client, db_session, test_family, test_parent_user, auth_headers):
    await _eb(db_session, test_family, on=False)
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 409 and r.json()["code"] == "early_bird_off"
    assert await _rules_notes(db_session) == []


async def test_non_parent_403(client, db_session, test_family, test_teen_user):
    await _eb(db_session, test_family)
    r = await client.post("/api/rules/announce", headers=await _login(client, "teen@test.com"))
    assert r.status_code == 403


async def _patch(client, headers, **body):
    return await client.patch("/api/families/me", json=body, headers=headers)


async def test_version_bump_auto_announces_ignoring_cap(
    client, db_session, test_family, test_parent_user, test_teen_user, auth_headers
):
    await _eb(db_session, test_family)
    assert (await client.post("/api/rules/announce", headers=auth_headers)).status_code == 200
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200, r.text
    assert len(await _rules_notes(db_session, test_family.id)) == 4  # 2 + 2 (cap ignored)


async def test_enabling_eb_announces(client, db_session, test_family, test_parent_user, auth_headers):
    await _eb(db_session, test_family, on=False)
    r = await _patch(client, auth_headers, early_bird_enabled=True)
    assert r.status_code == 200, r.text
    assert len(await _rules_notes(db_session)) == 1


async def test_unwatched_save_sends_nothing(client, db_session, test_family, test_parent_user, auth_headers):
    await _eb(db_session, test_family)
    r = await _patch(client, auth_headers, name="Renamed family")
    assert r.status_code == 200
    r = await _patch(client, auth_headers, early_bird_enabled=True)  # already on
    assert r.status_code == 200
    assert await _rules_notes(db_session) == []


async def test_bonus_pct_change_re_asks(
    client, db_session, test_family, test_parent_user, test_teen_user, auth_headers
):
    # The sheet shows the per-chore bonus %, so changing it is a new version.
    await _eb(db_session, test_family)
    r = await _patch(client, auth_headers, early_bird_bonus_pct=25)
    assert r.status_code == 200 and r.json()["rules_version"] == 2
    notes = await _rules_notes(db_session)
    assert {n.user_id for n in notes} == {test_parent_user.id, test_teen_user.id}


async def test_bump_with_eb_off_sends_nothing(client, db_session, test_family, test_parent_user, auth_headers):
    await _eb(db_session, test_family, on=False)
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200
    assert await _rules_notes(db_session) == []


async def _accept(db, user, family_id, version):
    db.add(RulesAcceptance(family_id=family_id, user_id=user.id, rules_version=version, snapshot={}))
    await db.commit()


async def test_announce_notifies_only_pending_members(
    client, db_session, test_family, test_parent_user, test_parent_user_2,
    test_teen_user, test_child_user, auth_headers
):
    # R2: the notice says "read and accept"; whoever already accepted the
    # current version has nothing to do and their link would open nothing.
    await _eb(db_session, test_family)
    v = test_family.rules_version
    await _accept(db_session, test_parent_user, test_family.id, v)
    await _accept(db_session, test_teen_user, test_family.id, v)
    # Neither an older version nor another family's acceptance counts.
    other = Family(name="Other")
    db_session.add(other)
    await db_session.commit()
    await _accept(db_session, test_parent_user_2, test_family.id, v - 1)
    await _accept(db_session, test_child_user, other.id, v)
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"sent": 2}
    notes = await _rules_notes(db_session)
    assert sorted(str(n.user_id) for n in notes) == sorted(
        [str(test_parent_user_2.id), str(test_child_user.id)])


async def test_announce_everyone_accepted_sends_zero_and_starts_no_cap(
    client, db_session, test_family, test_parent_user, test_teen_user, auth_headers
):
    await _eb(db_session, test_family)
    v = test_family.rules_version
    await _accept(db_session, test_parent_user, test_family.id, v)
    await _accept(db_session, test_teen_user, test_family.id, v)
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"sent": 0}
    assert await _rules_notes(db_session) == []
    # Nothing was written, so no hourly cap started: a newcomer can be told.
    db_session.add(User(email="new@test.com", password_hash=get_password_hash("x"), name="New",
                        role=UserRole.CHILD, family_id=test_family.id))
    await db_session.commit()
    r = await client.post("/api/rules/announce", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"sent": 1}


async def test_bump_after_everyone_accepted_notifies_everyone(
    client, db_session, test_family, test_parent_user, test_teen_user, auth_headers
):
    await _eb(db_session, test_family)
    v = test_family.rules_version
    await _accept(db_session, test_parent_user, test_family.id, v)
    await _accept(db_session, test_teen_user, test_family.id, v)
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200 and r.json()["rules_version"] == v + 1
    notes = await _rules_notes(db_session)
    assert sorted(str(n.user_id) for n in notes) == sorted(
        [str(test_parent_user.id), str(test_teen_user.id)])


async def test_bump_and_enable_in_one_save_announces_once(
    client, db_session, test_family, test_parent_user, test_teen_user, auth_headers
):
    await _eb(db_session, test_family, on=False)
    r = await _patch(client, auth_headers, early_bird_enabled=True, chore_cutoff="21:00")
    assert r.status_code == 200, r.text
    assert r.json()["rules_version"] == 2 and r.json()["early_bird_enabled"] is True
    notes = await _rules_notes(db_session)
    assert sorted(str(n.user_id) for n in notes) == sorted(
        [str(test_parent_user.id), str(test_teen_user.id)])


async def test_announce_failure_with_failing_rollback_does_not_fail_save(
    client, db_session, test_family, test_parent_user, auth_headers, monkeypatch
):
    await _eb(db_session, test_family)

    async def boom(*a, **k):
        raise RuntimeError("push down")

    async def rollback_boom(*a, **k):
        raise RuntimeError("connection gone")

    monkeypatch.setattr(RulesService, "announce", boom)
    monkeypatch.setattr(db_session, "rollback", rollback_boom)
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200, r.text
    assert r.json()["chore_cutoff"] == "21:00" and r.json()["rules_version"] == 2


async def test_announce_failure_does_not_fail_save(
    client, db_session, test_family, test_parent_user, auth_headers, monkeypatch
):
    await _eb(db_session, test_family)

    async def boom(*a, **k):
        raise RuntimeError("push down")

    monkeypatch.setattr(RulesService, "announce", boom)
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200, r.text
    assert r.json()["chore_cutoff"] == "21:00"
    await db_session.refresh(test_family)
    assert test_family.rules_version == 2
