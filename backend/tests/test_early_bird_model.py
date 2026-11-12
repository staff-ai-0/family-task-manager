"""Early Bird data model: columns, enum values, unique week, settings, export."""
import io
import json
import zipfile
from datetime import date, datetime, time, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import create_access_token
from app.models.cash_transaction import CashTransaction, CashTransactionType
from app.models.early_bird_week import EarlyBirdWeek
from app.models.family import Family
from app.models.task_assignment import AssignmentStatus, TaskAssignment
from app.models.task_template import TaskTemplate

MON = date(2026, 11, 2)


def _auth(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


async def test_family_defaults(db_session):
    fam = Family(name="Defaults")
    db_session.add(fam)
    await db_session.commit()
    await db_session.refresh(fam)
    assert fam.early_bird_enabled is False
    assert fam.early_bird_enabled_at is None
    assert fam.early_bird_deadline == time(11, 0)
    assert fam.early_bird_bonus_pct == 20
    assert fam.early_bird_week_pct == 5
    assert fam.early_bird_streak_cents == 50000
    assert fam.early_bird_days is None


async def _template(db, fam, user):
    t = TaskTemplate(title="Dishes", points=10, family_id=fam.id, created_by=user.id)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    assert t.early_bird_exempt is False
    return t


async def test_assignment_taken_status_roundtrip(db_session, test_family, test_teen_user):
    t = await _template(db_session, test_family, test_teen_user)
    a = TaskAssignment(
        template_id=t.id, assigned_to=test_teen_user.id, family_id=test_family.id,
        status=AssignmentStatus.TAKEN, assigned_date=MON, week_of=MON,
        taken_by=test_teen_user.id, taken_at=datetime.now(timezone.utc),
    )
    db_session.add(a)
    await db_session.commit()
    aid = a.id
    db_session.expire_all()
    got = (await db_session.execute(select(TaskAssignment).where(TaskAssignment.id == aid))).scalar_one()
    assert got.status == AssignmentStatus.TAKEN
    assert got.taken_from_id is None and got.early_bonus_points is None


async def test_cash_bonus_type_roundtrip(db_session, test_family, test_teen_user):
    c = CashTransaction(
        type=CashTransactionType.BONUS, amount_cents=50000, user_id=test_teen_user.id,
        family_id=test_family.id, balance_before=0, balance_after=50000,
    )
    db_session.add(c)
    await db_session.commit()
    cid = c.id
    db_session.expire_all()
    got = (await db_session.execute(select(CashTransaction).where(CashTransaction.id == cid))).scalar_one()
    assert got.type == CashTransactionType.BONUS


def _week(fam, user, **kw):
    return EarlyBirdWeek(family_id=fam.id, user_id=user.id, week_of=MON, result="early", run_weeks=1, **kw)


async def test_early_bird_week_unique(db_session, test_family, test_teen_user):
    db_session.add(_week(test_family, test_teen_user))
    await db_session.commit()
    db_session.add(_week(test_family, test_teen_user))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_early_bird_week_result_check(db_session, test_family, test_teen_user):
    w = _week(test_family, test_teen_user)
    w.result = "nope"
    db_session.add(w)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_enabled_at_restamped_on_reenable(client, auth_headers, db_session, test_family):
    on = {"early_bird_enabled": True}
    r = await client.patch("/api/families/me", json=on, headers=auth_headers)
    assert r.status_code == 200, r.text
    await db_session.refresh(test_family)
    t1 = test_family.early_bird_enabled_at
    assert t1 is not None
    # a second "on" while already on does not re-stamp
    await client.patch("/api/families/me", json=on, headers=auth_headers)
    await db_session.refresh(test_family)
    assert test_family.early_bird_enabled_at == t1
    await client.patch("/api/families/me", json={"early_bird_enabled": False}, headers=auth_headers)
    await client.patch("/api/families/me", json=on, headers=auth_headers)
    await db_session.refresh(test_family)
    assert test_family.early_bird_enabled_at > t1


async def test_family_update_validation(client, auth_headers, db_session, test_family):
    async def patch(**body):
        return await client.patch("/api/families/me", json=body, headers=auth_headers)

    assert (await patch(early_bird_deadline="06:55")).status_code == 422
    assert (await patch(early_bird_deadline="22:05")).status_code == 422
    assert (await patch(early_bird_deadline="11:03")).status_code == 422
    assert (await patch(early_bird_deadline="nope")).status_code == 422
    r = await patch(early_bird_deadline="11:00")
    assert r.status_code == 200 and r.json()["early_bird_deadline"] == "11:00"
    r = await patch(early_bird_deadline="22:00")
    assert r.status_code == 200 and r.json()["early_bird_deadline"] == "22:00"
    assert (await patch(early_bird_days=[7])).status_code == 422
    assert (await patch(early_bird_days=[])).status_code == 422
    r = await patch(early_bird_days=[4, 0, 0])
    assert r.status_code == 200 and r.json()["early_bird_days"] == [0, 4]
    assert (await patch(early_bird_week_pct=51)).status_code == 422
    assert (await patch(early_bird_bonus_pct=101)).status_code == 422
    r = await patch(early_bird_enabled=None)
    assert r.status_code == 200 and r.json()["early_bird_enabled"] is False
    body = (await client.get("/api/families/me", headers=auth_headers)).json()
    assert body["early_bird_bonus_pct"] == 20 and body["early_bird_streak_cents"] == 50000


async def test_template_exempt_flag_roundtrip(client, auth_headers):
    r = await client.post("/api/task-templates/", json={
        "title": "Trash", "points": 5, "early_bird_exempt": True,
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    assert r.json()["early_bird_exempt"] is True
    r = await client.put(f"/api/task-templates/{r.json()['id']}", json={"early_bird_exempt": False}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["early_bird_exempt"] is False


async def test_export_includes_early_bird_weeks(client, db_session, test_family, test_parent_user, test_teen_user):
    db_session.add(_week(test_family, test_teen_user))
    await db_session.commit()
    r = await client.get("/api/families/export", headers=_auth(test_parent_user))
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    rows = json.loads(zf.read("progress/early_bird_weeks.json"))
    assert len(rows) == 1 and rows[0]["result"] == "early"


async def test_switching_off_records_the_period_it_closes(client, auth_headers, db_session, test_family):
    on, off = {"early_bird_enabled": True}, {"early_bird_enabled": False}
    await client.patch("/api/families/me", json=on, headers=auth_headers)
    await db_session.refresh(test_family)
    t1 = test_family.early_bird_enabled_at
    await client.patch("/api/families/me", json=off, headers=auth_headers)
    await db_session.refresh(test_family)
    periods = test_family.early_bird_past_periods
    assert len(periods) == 1
    start, end = (datetime.fromisoformat(x) for x in periods[0])
    assert start == t1 and end >= t1
    # a second "off" while already off records nothing more
    await client.patch("/api/families/me", json=off, headers=auth_headers)
    await db_session.refresh(test_family)
    assert len(test_family.early_bird_past_periods) == 1
