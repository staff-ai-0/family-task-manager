"""UX-D4b mystery box: the two tables, their guards, the family setting, the export."""
import importlib.util
import pathlib
import re
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.mystery import MysteryBox, MysterySurprise
from app.services.family_export_service import EXPORTED_FAMILY_TABLES
from app.services.progress_service import ProgressService

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "2026_10_03_mystery_box.py"
RESET_TO_NULL = re.compile(r"^\s*UPDATE\s+families\s+SET\s+mystery_box_points\s*=\s*NULL\s*;?\s*$", re.IGNORECASE)


class _RecordingOp:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("mystery_box", MIGRATION)
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
    assert mod.revision == "mystery_box" and mod.down_revision == "teen_checkins"


def test_existing_families_start_undecided_and_new_ones_at_twenty():
    calls = _run("upgrade")
    adds = [(i, a) for i, (n, a, _k) in enumerate(calls) if n == "add_column" and a[0] == "families"]
    assert len(adds) == 1
    at, (_table, column) = adds[0]
    assert column.name == "mystery_box_points" and column.nullable is True
    assert str(column.server_default.arg) == "20"
    resets = [i for i, (n, a, _k) in enumerate(calls) if n == "execute" and RESET_TO_NULL.match(str(a[0]))]
    assert len(resets) == 1 and resets[0] > at                  # the reset runs AFTER the column exists
    tables = [a[0] for n, a, _k in calls if n == "create_table"]
    assert tables == ["mystery_surprises", "mystery_boxes"]


def test_reverse_migration_removes_everything():
    calls = _run("downgrade")
    assert ("drop_table", ("mystery_boxes",), {}) in calls
    assert ("drop_table", ("mystery_surprises",), {}) in calls
    assert ("drop_column", ("families", "mystery_box_points"), {}) in calls


async def _today(db, family_id):
    today, _tz = await ProgressService.family_today(db, family_id)
    return today


def _box(kid, day, **kw):
    base = dict(family_id=kid.family_id, user_id=kid.id, day=day, kind=None, surprise_id=None, surprise_title=None,
                surprise_emoji=None, points=0, opened_at=None, created_at=datetime.now(timezone.utc))
    base.update(kw)
    return MysteryBox(**base)


class TestTables:
    async def test_a_closed_box_and_a_surprise_are_stored(self, db_session, test_family, test_parent_user, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add_all([
            _box(test_child_user, today),
            MysterySurprise(family_id=test_family.id, title="Pick dessert tonight", emoji="🍨", created_by=test_parent_user.id),
        ])
        await db_session.commit()
        box = (await db_session.execute(select(MysteryBox))).scalar_one()
        assert box.opened_at is None and box.kind is None and box.points == 0
        jar = (await db_session.execute(select(MysterySurprise))).scalar_one()
        assert (jar.title, jar.emoji) == ("Pick dessert tonight", "🍨")

    async def test_one_box_per_kid_per_day(self, db_session, test_family, test_child_user):
        today = await _today(db_session, test_family.id)
        db_session.add(_box(test_child_user, today))
        await db_session.commit()
        db_session.add(_box(test_child_user, today))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    @pytest.mark.parametrize("bad", [
        dict(kind="coins"),                                              # unknown kind
        dict(kind="points", points=12),                                  # a kind without opened_at
        dict(opened_at=datetime.now(timezone.utc)),                      # opened without a kind
        dict(kind="points", points=-1, opened_at=datetime.now(timezone.utc)),
    ])
    async def test_the_database_refuses_inconsistent_boxes(self, db_session, test_family, test_child_user, bad):
        today = await _today(db_session, test_family.id)
        db_session.add(_box(test_child_user, today, **bad))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()


class TestFamilySetting:
    async def test_a_test_family_reads_twenty_by_default(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["mystery_box_points"] == 20

    async def test_parent_sets_it_within_bounds(self, client, auth_headers, db_session, test_family):
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 35}, headers=auth_headers)).json()["mystery_box_points"] == 35
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 0}, headers=auth_headers)).status_code == 200
        assert (await client.patch("/api/families/me", json={"mystery_box_points": -1}, headers=auth_headers)).status_code == 422
        assert (await client.patch("/api/families/me", json={"mystery_box_points": 501}, headers=auth_headers)).status_code == 422
        await db_session.refresh(test_family)
        assert test_family.mystery_box_points == 0

    async def test_an_undecided_family_reads_null(self, client, auth_headers, db_session, test_family):
        test_family.mystery_box_points = None
        await db_session.commit()
        assert (await client.get("/api/families/me", headers=auth_headers)).json()["mystery_box_points"] is None


def test_both_tables_are_part_of_the_family_export():
    assert {"mystery_surprises", "mystery_boxes"} <= EXPORTED_FAMILY_TABLES
