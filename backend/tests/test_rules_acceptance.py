"""Rules acceptance: per-member record + /api/rules/{status,accept,acceptances}."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.core.security import get_password_hash
from app.models.family import Family
from app.models.rules_acceptance import RulesAcceptance
from app.models.user import User, UserRole
from app.services.family_export_service import EXPORTED_FAMILY_TABLES


async def _login(client, email):
    r = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _enable(db, family, on=True):
    family.early_bird_enabled = on
    family.early_bird_enabled_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db.commit()


async def _count(db, user_id):
    return (await db.execute(
        select(func.count()).select_from(RulesAcceptance).where(RulesAcceptance.user_id == user_id)
    )).scalar_one()


@pytest.mark.parametrize("email", ["teen@test.com", "child@test.com", "parent@test.com"])
async def test_status_required_every_role(client, db_session, test_family, test_teen_user,
                                          test_child_user, test_parent_user, email):
    await _enable(db_session, test_family)
    r = await client.get("/api/rules/status", headers=await _login(client, email))
    assert r.status_code == 200
    b = r.json()
    assert b["required"] is True and b["accepted_at"] is None
    assert b["version"] == test_family.rules_version
    rules = b["rules"]
    assert set(rules) == {"version", "deadline", "cutoff", "grab_end", "alarm_1", "alarm_2",
                          "streak_cents", "chore_bonus_pct", "floor_pct", "bonus_tiers"}
    assert rules["version"] == test_family.rules_version
    assert rules["deadline"] == test_family.early_bird_deadline.strftime("%H:%M")
    assert rules["cutoff"] == test_family.chore_cutoff.strftime("%H:%M")
    assert rules["grab_end"] == test_family.grab_window_end.strftime("%H:%M")
    assert rules["alarm_1"] == test_family.teen_alarm_1.strftime("%H:%M")
    assert rules["alarm_2"] == test_family.teen_alarm_2.strftime("%H:%M")
    assert rules["streak_cents"] == test_family.early_bird_streak_cents
    assert rules["chore_bonus_pct"] == test_family.early_bird_bonus_pct
    assert rules["floor_pct"] == 60
    assert rules["bonus_tiers"] == [
        {"early_pct": 80, "bonus_pct": 5}, {"early_pct": 90, "bonus_pct": 10},
        {"early_pct": 100, "bonus_pct": 15}]


async def test_status_not_required_when_off(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family, on=False)
    r = await client.get("/api/rules/status", headers=await _login(client, "teen@test.com"))
    assert r.json()["required"] is False


async def test_accept_records_snapshot(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    h = await _login(client, "teen@test.com")
    v = test_family.rules_version
    r = await client.post("/api/rules/accept", json={"version": v}, headers=h)
    assert r.status_code == 200
    row = (await db_session.execute(
        select(RulesAcceptance).where(RulesAcceptance.user_id == test_teen_user.id))).scalar_one()
    assert row.family_id == test_family.id and row.rules_version == v
    assert row.snapshot["version"] == v and row.snapshot["floor_pct"] == 60
    s = (await client.get("/api/rules/status", headers=h)).json()
    assert s["required"] is False and s["accepted_at"] is not None


async def test_double_accept_one_row(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    h = await _login(client, "teen@test.com")
    v = test_family.rules_version
    assert (await client.post("/api/rules/accept", json={"version": v}, headers=h)).status_code == 200
    assert (await client.post("/api/rules/accept", json={"version": v}, headers=h)).status_code == 200
    assert await _count(db_session, test_teen_user.id) == 1


async def test_stale_version_409(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    h = await _login(client, "teen@test.com")
    r = await client.post("/api/rules/accept", json={"version": test_family.rules_version + 1}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "stale_version"
    assert await _count(db_session, test_teen_user.id) == 0


async def test_version_bump_requires_again(client, db_session, test_family, test_teen_user):
    await _enable(db_session, test_family)
    h = await _login(client, "teen@test.com")
    v = test_family.rules_version
    await client.post("/api/rules/accept", json={"version": v}, headers=h)
    test_family.rules_version = v + 1
    await db_session.commit()
    s = (await client.get("/api/rules/status", headers=h)).json()
    assert s["required"] is True and s["version"] == v + 1
    assert (await client.post("/api/rules/accept", json={"version": v + 1}, headers=h)).status_code == 200
    assert await _count(db_session, test_teen_user.id) == 2


async def test_acceptances_list(client, db_session, test_family, test_parent_user,
                                test_teen_user, test_child_user):
    await _enable(db_session, test_family)
    inactive = User(email=f"i-{uuid4().hex[:6]}@example.com", password_hash=get_password_hash("password123"),
                    name="Gone", role=UserRole.TEEN, family_id=test_family.id, email_verified=True,
                    is_active=False)
    other = Family(name="Other")
    db_session.add_all([inactive, other])
    await db_session.commit()
    stranger = User(email=f"s-{uuid4().hex[:6]}@example.com", password_hash=get_password_hash("password123"),
                    name="Stranger", role=UserRole.TEEN, family_id=other.id, email_verified=True)
    db_session.add(stranger)
    await db_session.commit()
    await client.post("/api/rules/accept", json={"version": test_family.rules_version},
                      headers=await _login(client, "teen@test.com"))
    r = await client.get("/api/rules/acceptances", headers=await _login(client, "parent@test.com"))
    assert r.status_code == 200
    by_id = {x["user_id"]: x for x in r.json()}
    assert set(by_id) == {str(test_parent_user.id), str(test_teen_user.id), str(test_child_user.id)}
    assert by_id[str(test_teen_user.id)]["accepted_at"] is not None
    assert by_id[str(test_child_user.id)]["accepted_at"] is None
    assert by_id[str(test_teen_user.id)]["role"] == "teen"
    assert by_id[str(test_teen_user.id)]["name"] == "Test Teen"


async def test_acceptances_only_current_version(client, db_session, test_family, test_parent_user,
                                                test_teen_user):
    await _enable(db_session, test_family)
    h = await _login(client, "teen@test.com")
    await client.post("/api/rules/accept", json={"version": test_family.rules_version}, headers=h)
    test_family.rules_version += 1
    await db_session.commit()
    r = await client.get("/api/rules/acceptances", headers=await _login(client, "parent@test.com"))
    assert {x["user_id"]: x["accepted_at"] for x in r.json()}[str(test_teen_user.id)] is None


async def test_acceptances_parent_only(client, db_session, test_family, test_teen_user):
    r = await client.get("/api/rules/acceptances", headers=await _login(client, "teen@test.com"))
    assert r.status_code == 403


async def test_unauthenticated_401(client):
    assert (await client.get("/api/rules/status")).status_code == 401
    assert (await client.post("/api/rules/accept", json={"version": 1})).status_code == 401
    assert (await client.get("/api/rules/acceptances")).status_code == 401


def test_export_registry_includes_table():
    assert "rules_acceptances" in EXPORTED_FAMILY_TABLES
