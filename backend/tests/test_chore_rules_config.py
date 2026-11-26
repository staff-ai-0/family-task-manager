"""Chore rules config: columns, defaults, validation, rules_version bump."""
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
    assert body["teen_alarm_1"] == "15:00" and body["teen_alarm_2"] == "19:00"
    assert body["rules_version"] == 1
    # Retired with the evening release: the columns stay in the table, unread.
    assert "chore_cutoff" not in body and "grab_window_end" not in body


async def test_update_bumps_rules_version(client, auth_headers, db_session, test_family):
    async def version():
        await db_session.refresh(test_family)
        return test_family.rules_version

    assert await version() == 1
    r = await _patch(client, auth_headers, early_bird_deadline="10:00")
    assert r.status_code == 200, r.text
    assert r.json()["early_bird_deadline"] == "10:00" and r.json()["rules_version"] == 2
    # unchanged PUT keeps the value
    r = await _patch(client, auth_headers, early_bird_deadline="10:00", name=test_family.name)
    assert r.status_code == 200 and await version() == 2
    r = await _patch(client, auth_headers, early_bird_streak_cents=40000)
    assert r.status_code == 200 and await version() == 3
    r = await _patch(client, auth_headers, teen_alarm_1="14:00", teen_alarm_2="18:00")
    assert r.status_code == 200 and await version() == 4
    # the per-chore bonus % is shown in (and snapshotted by) the rules sheet
    r = await _patch(client, auth_headers, early_bird_bonus_pct=25)
    assert r.status_code == 200 and await version() == 5
    r = await _patch(client, auth_headers, early_bird_bonus_pct=25)  # unchanged
    assert r.status_code == 200 and await version() == 5
    # a non-watched field does not bump
    r = await _patch(client, auth_headers, name="Renamed family")
    assert r.status_code == 200 and await version() == 5


async def test_retired_fields_are_ignored(client, auth_headers, db_session, test_family):
    """A settings page opened before the deploy still posts the two retired
    fields. The save must succeed, change nothing and re-ask nobody."""
    r = await _patch(client, auth_headers, chore_cutoff="21:00", grab_window_end="23:00",
                     name="Still saves")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Still saves" and body["rules_version"] == 1
    assert "chore_cutoff" not in body and "grab_window_end" not in body
    await db_session.refresh(test_family)
    assert test_family.chore_cutoff == time(20, 30)
    assert test_family.grab_window_end == time(22, 30)
    # even a value the old validators refused is ignored, not a 422
    assert (await _patch(client, auth_headers, chore_cutoff="03:33")).status_code == 200


async def test_deadline_is_not_bounded_by_a_cutoff(client, auth_headers):
    """21:00 was refused while the stored cutoff was 20:30."""
    r = await _patch(client, auth_headers, early_bird_deadline="21:00")
    assert r.status_code == 200 and r.json()["early_bird_deadline"] == "21:00"


async def test_alarm_order(client, auth_headers):
    assert (await _patch(client, auth_headers, teen_alarm_1="19:00", teen_alarm_2="15:00")).status_code == 400
    assert (await _patch(client, auth_headers, teen_alarm_1="15:00", teen_alarm_2="15:00")).status_code == 400
    assert (await _patch(client, auth_headers, teen_alarm_1="05:55")).status_code == 422
    assert (await _patch(client, auth_headers, teen_alarm_1="15:03")).status_code == 422
    assert (await _patch(client, auth_headers, teen_alarm_2="23:05")).status_code == 422
    r = await _patch(client, auth_headers, teen_alarm_1="06:00", teen_alarm_2="20:25")
    assert r.status_code == 200


async def test_alarm_after_the_old_cutoff_is_accepted(client, auth_headers):
    """Alarms had to be before the 20:30 cutoff; the day now ends at midnight."""
    r = await _patch(client, auth_headers, teen_alarm_1="21:00", teen_alarm_2="23:00")
    assert r.status_code == 200, r.text
    assert (r.json()["teen_alarm_1"], r.json()["teen_alarm_2"]) == ("21:00", "23:00")
    assert r.json()["rules_version"] == 2
