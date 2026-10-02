"""UX-D4a: the family switch for smart reminders."""
import importlib.util
import pathlib

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_10_01_family_smart_reminders.py"
)


class _RecordingOp:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("family_smart_reminders", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_chain():
    mod = _load()
    assert mod.revision == "family_smart_reminders"
    assert mod.down_revision == "weekly_quests"


def test_upgrade_adds_one_not_null_column_defaulting_to_true():
    mod = _load()
    op = _RecordingOp()
    mod.op = op
    mod.upgrade()
    assert [name for name, _a, _k in op.calls] == ["add_column"]
    _name, args, _kw = op.calls[0]
    column = args[1]
    assert args[0] == "families" and column.name == "smart_reminders_enabled"
    assert column.nullable is False
    assert str(column.server_default.arg) == "true"


def test_reverse_migration_drops_only_that_column():
    mod = _load()
    op = _RecordingOp()
    mod.op = op
    mod.downgrade()
    assert op.calls == [("drop_column", ("families", "smart_reminders_enabled"), {})]


class TestFamilySetting:
    async def test_on_by_default(self, client, auth_headers, test_family):
        r = await client.get("/api/families/me", headers=auth_headers)
        assert r.status_code == 200 and r.json()["smart_reminders_enabled"] is True

    async def test_parent_can_switch_it_off_and_on(self, client, auth_headers, db_session, test_family):
        r = await client.patch("/api/families/me", json={"smart_reminders_enabled": False}, headers=auth_headers)
        assert r.status_code == 200 and r.json()["smart_reminders_enabled"] is False
        await db_session.refresh(test_family)
        assert test_family.smart_reminders_enabled is False
        r = await client.patch("/api/families/me", json={"smart_reminders_enabled": True}, headers=auth_headers)
        assert r.json()["smart_reminders_enabled"] is True

    async def test_other_updates_leave_it_alone(self, client, auth_headers, db_session, test_family):
        await client.patch("/api/families/me", json={"smart_reminders_enabled": False}, headers=auth_headers)
        await client.patch("/api/families/me", json={"quest_bonus_points": 30}, headers=auth_headers)
        await db_session.refresh(test_family)
        assert test_family.smart_reminders_enabled is False

    async def test_a_kid_cannot_change_it(self, client, test_child_user, db_session, test_family):
        login = await client.post("/api/auth/login", json={"email": "child@test.com", "password": "password123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = await client.patch("/api/families/me", json={"smart_reminders_enabled": False}, headers=headers)
        assert r.status_code in (401, 403)
        await db_session.refresh(test_family)
        assert test_family.smart_reminders_enabled is True
