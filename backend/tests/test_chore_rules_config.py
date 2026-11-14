"""Chore rules v2 config: columns, defaults, validation, rules_version bump."""
from datetime import time

from sqlalchemy import text

from app.models.family import Family


async def _patch(client, headers, **body):
    return await client.patch("/api/families/me", json=body, headers=headers)


async def test_defaults(db_session):
    fam = Family(name="Rules defaults")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    assert fam.chore_cutoff == time(20, 30)
    assert fam.grab_window_end == time(22, 30)
    assert fam.teen_alarm_1 == time(15, 0)
    assert fam.teen_alarm_2 == time(19, 0)
    assert fam.rules_version == 1
    assert fam.early_bird_streak_cents == 38000


async def test_existing_row_keeps_old_streak_default(db_session):
    # A row written before the change (raw SQL, the model default not applied)
    # keeps the server_default: the new 38000 is a Python default only.
    await db_session.execute(text("INSERT INTO families (id, name, is_active, created_at, updated_at) "
        "VALUES (gen_random_uuid(), 'old', true, now(), now())"))
    await db_session.commit()
    got = (await db_session.execute(text(
        "SELECT early_bird_streak_cents FROM families WHERE name = 'old'"))).scalar_one()
    assert got == 50000


async def test_response_exposes_fields(client, auth_headers):
    body = (await client.get("/api/families/me", headers=auth_headers)).json()
    assert body["chore_cutoff"] == "20:30" and body["grab_window_end"] == "22:30"
    assert body["teen_alarm_1"] == "15:00" and body["teen_alarm_2"] == "19:00"
    assert body["rules_version"] == 1


async def test_update_bumps_rules_version(client, auth_headers, db_session, test_family):
    async def version():
        await db_session.refresh(test_family)
        return test_family.rules_version

    assert await version() == 1
    r = await _patch(client, auth_headers, chore_cutoff="21:00")
    assert r.status_code == 200, r.text
    assert r.json()["chore_cutoff"] == "21:00" and r.json()["rules_version"] == 2
    # unchanged PUT keeps the value
    r = await _patch(client, auth_headers, chore_cutoff="21:00", name=test_family.name)
    assert r.status_code == 200 and await version() == 2
    r = await _patch(client, auth_headers, early_bird_deadline="10:00")
    assert r.status_code == 200 and await version() == 3
    r = await _patch(client, auth_headers, early_bird_streak_cents=40000)
    assert r.status_code == 200 and await version() == 4
    r = await _patch(client, auth_headers, grab_window_end="23:00")
    assert r.status_code == 200 and await version() == 5
    r = await _patch(client, auth_headers, teen_alarm_1="14:00", teen_alarm_2="18:00")
    assert r.status_code == 200 and await version() == 6
    # the per-chore bonus % is shown in (and snapshotted by) the rules sheet
    r = await _patch(client, auth_headers, early_bird_bonus_pct=25)
    assert r.status_code == 200 and await version() == 7
    r = await _patch(client, auth_headers, early_bird_bonus_pct=25)  # unchanged
    assert r.status_code == 200 and await version() == 7
    # a non-watched field does not bump
    r = await _patch(client, auth_headers, name="Renamed family")
    assert r.status_code == 200 and await version() == 7


async def test_validation_rejects_cutoff_before_deadline(client, auth_headers):
    r = await _patch(client, auth_headers, early_bird_deadline="11:00", chore_cutoff="11:00")
    assert r.status_code in (400, 422)
    assert (await _patch(client, auth_headers, chore_cutoff="16:55")).status_code == 422
    assert (await _patch(client, auth_headers, chore_cutoff="23:05")).status_code == 422
    assert (await _patch(client, auth_headers, chore_cutoff="20:33")).status_code == 422
    # deadline moved past the stored cutoff (20:30)
    assert (await _patch(client, auth_headers, early_bird_deadline="21:00")).status_code == 400
    r = await _patch(client, auth_headers, early_bird_deadline="21:00", chore_cutoff="22:00")
    assert r.status_code == 200
    # grab window must end after the cutoff and by 23:30
    assert (await _patch(client, auth_headers, grab_window_end="22:00")).status_code == 400
    assert (await _patch(client, auth_headers, grab_window_end="23:35")).status_code == 422


async def test_alarm_order(client, auth_headers):
    assert (await _patch(client, auth_headers, teen_alarm_1="19:00", teen_alarm_2="15:00")).status_code == 400
    assert (await _patch(client, auth_headers, teen_alarm_1="15:00", teen_alarm_2="15:00")).status_code == 400
    assert (await _patch(client, auth_headers, teen_alarm_1="05:55")).status_code == 422
    assert (await _patch(client, auth_headers, teen_alarm_1="15:03")).status_code == 422
    # alarm after, or AT, the stored cutoff (20:30): an alarm at the cutoff
    # would say "due by 20:30" at the moment the chores stop being the teen's.
    assert (await _patch(client, auth_headers, teen_alarm_2="21:00")).status_code == 400
    r = await _patch(client, auth_headers, teen_alarm_2="20:30")
    assert r.status_code == 400 and "before chore_cutoff" in r.text
    r = await _patch(client, auth_headers, teen_alarm_1="06:00", teen_alarm_2="20:25")
    assert r.status_code == 200
