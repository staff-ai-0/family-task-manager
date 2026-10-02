"""Jarvis teen check-in: the table, its guards, the family switch, the export."""
import importlib.util
import pathlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.models.task_assignment import ApprovalStatus, AssignmentStatus, TaskAssignment
from app.models.task_template import AssignmentType, TaskTemplate
from app.models.teen_checkin import TeenCheckin
from app.services.family_export_service import EXPORTED_FAMILY_TABLES
from app.services.progress_service import ProgressService

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_10_01_teen_checkins.py"
)


class _RecordingOp:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("teen_checkins", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(direction):
    mod = _load()
    op = _RecordingOp()
    mod.op = op
    getattr(mod, direction)()
    return op.calls


def test_revision_chain():
    mod = _load()
    assert mod.revision == "teen_checkins"
    assert mod.down_revision == "family_smart_reminders"


def test_upgrade_adds_an_undecided_switch_and_the_table():
    calls = _run("upgrade")
    adds = {a[1].name: a for n, a, _k in calls if n == "add_column"}
    assert set(adds) == {"teen_checkin_enabled", "teen_checkin_decided_at"}
    assert all(a[0] == "families" for a in adds.values())
    column = adds["teen_checkin_enabled"][1]
    assert column.nullable is True
    assert column.server_default is None                       # every family starts undecided
    assert adds["teen_checkin_decided_at"][1].nullable is True
    indexes = {a[0] for n, a, _k in calls if n == "create_index"}
    assert "ix_teen_checkins_assignment_id" in indexes
    tables = [a for n, a, _k in calls if n == "create_table"]
    assert [t[0] for t in tables] == ["teen_checkins"]
    names = {getattr(c, "name", None) for c in tables[0][1:]}
    assert {"uq_teen_checkins_family_user_assignment", "ck_teen_checkins_reason_iff_answered",
            "ck_teen_checkins_note_reason", "ck_teen_checkins_note_len"} <= names
    assert "title" not in names and "template_title" not in names


def test_reverse_migration_removes_both():
    calls = _run("downgrade")
    assert ("drop_table", ("teen_checkins",), {}) in calls
    assert ("drop_column", ("families", "teen_checkin_enabled"), {}) in calls
    assert ("drop_column", ("families", "teen_checkin_decided_at"), {}) in calls


async def _assignment(db, teen):
    today, _tz = await ProgressService.family_today(db, teen.family_id)
    template = TaskTemplate(id=uuid4(), title="Clean Diego's room", points=15, interval_days=1,
                            assignment_type=AssignmentType.AUTO, is_bonus=False, is_active=True,
                            family_id=teen.family_id)
    db.add(template)
    await db.commit()
    day = today - timedelta(days=1)
    a = TaskAssignment(family_id=teen.family_id, template_id=template.id, assigned_to=teen.id,
                       status=AssignmentStatus.OVERDUE, approval_status=ApprovalStatus.NONE,
                       assigned_date=day, week_of=day - timedelta(days=day.weekday()))
    db.add(a)
    await db.commit()
    return a


def _row(teen, assignment, **kw):
    base = dict(family_id=teen.family_id, user_id=teen.id, assignment_id=assignment.id, trigger="late",
                outcome="answered", reason="too_hard", note=None, days_late=1, points=15, lang="en",
                created_at=datetime.now(timezone.utc))
    base.update(kw)
    return TeenCheckin(**base)


class TestTable:
    async def test_a_valid_answer_is_stored(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert (row.trigger, row.outcome, row.reason, row.note) == ("late", "answered", "too_hard", None)
        assert not hasattr(row, "title")

    @pytest.mark.parametrize("bad", [
        dict(outcome="answered", reason=None),                       # an answer needs a reason
        dict(outcome="dismissed", reason="forgot"),                  # a dismissal has none
        dict(reason="too_hard", note="my brother never does his"),   # notes only for app_problem / other
        dict(reason="other", note="x" * 201),                        # 200 characters at most
        dict(reason="because"),                                      # not one of the seven
        dict(trigger="bored"),
        dict(outcome="maybe"),
        dict(days_late=-1),
    ])
    async def test_the_database_refuses_bad_rows(self, db_session, test_teen_user, bad):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a, **bad))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_notes_are_allowed_for_the_two_open_reasons(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a, reason="app_problem", note="x" * 200))
        await db_session.commit()

    async def test_a_chore_is_asked_about_once(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        db_session.add(_row(test_teen_user, a, outcome="dismissed", reason=None))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_the_row_survives_its_chore(self, db_session, test_teen_user):
        a = await _assignment(db_session, test_teen_user)
        db_session.add(_row(test_teen_user, a))
        await db_session.commit()
        await db_session.execute(delete(TaskAssignment).where(TaskAssignment.id == a.id))
        await db_session.commit()
        db_session.expire_all()
        row = (await db_session.execute(select(TeenCheckin))).scalar_one()
        assert row.assignment_id is None and row.reason == "too_hard"


class TestFamilySwitch:
    async def test_every_family_starts_undecided(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["teen_checkin_enabled"] is None

    async def test_a_parent_can_turn_it_on_and_off(self, client, auth_headers, db_session, test_family):
        for value in (True, False):
            r = await client.patch("/api/families/me", json={"teen_checkin_enabled": value}, headers=auth_headers)
            assert r.status_code == 200 and r.json()["teen_checkin_enabled"] is value
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is False

    async def test_other_updates_leave_it_alone(self, client, auth_headers, db_session, test_family):
        await client.patch("/api/families/me", json={"teen_checkin_enabled": True}, headers=auth_headers)
        await db_session.refresh(test_family)
        decided = test_family.teen_checkin_decided_at
        await client.patch("/api/families/me", json={"quest_bonus_points": 30}, headers=auth_headers)
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is True
        assert test_family.teen_checkin_decided_at == decided      # not a new decision

    async def test_the_decision_is_timestamped(self, client, auth_headers, db_session, test_family):
        assert test_family.teen_checkin_decided_at is None
        before = datetime.now(timezone.utc) - timedelta(seconds=5)
        r = await client.patch("/api/families/me", json={"teen_checkin_enabled": False}, headers=auth_headers)
        assert r.json()["teen_checkin_decided_at"] is not None
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_decided_at >= before       # a "no" is a decision too

    async def test_a_teen_cannot_change_it(self, client, db_session, test_family, test_teen_user):
        login = await client.post("/api/auth/login", json={"email": "teen@test.com", "password": "password123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.patch("/api/families/me", json={"teen_checkin_enabled": True}, headers=headers)
        assert r.status_code in (401, 403)
        await db_session.refresh(test_family)
        assert test_family.teen_checkin_enabled is None


def test_the_table_is_part_of_the_family_export():
    assert "teen_checkins" in EXPORTED_FAMILY_TABLES
