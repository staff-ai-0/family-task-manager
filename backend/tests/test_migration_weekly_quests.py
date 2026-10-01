"""The weekly_quests migration's handling of families.quest_bonus_points.

Alembic itself is covered by CI's upgrade/round-trip job; this pins the
opt-in rule: the column is nullable with a default of 20 for families created
later, and every family that already exists is reset to NULL (undecided —
quests off until a parent answers the one-time card on the parent hub).
"""
import importlib.util
import pathlib
import re

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "migrations" / "versions" / "2026_10_01_weekly_quests.py"
)

RESET_TO_NULL = re.compile(
    r"^\s*UPDATE\s+families\s+SET\s+quest_bonus_points\s*=\s*NULL\s*;?\s*$", re.IGNORECASE
)


class _RecordingOp:
    """Stands in for alembic's `op`: records every call, in order."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def _load():
    spec = importlib.util.spec_from_file_location("weekly_quests", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _upgrade_calls():
    mod = _load()
    op = _RecordingOp()
    mod.op = op
    mod.upgrade()
    return op.calls


def _bonus_column_adds(calls):
    return [
        (i, args) for i, (name, args, _kw) in enumerate(calls)
        if name == "add_column" and args[0] == "families" and args[1].name == "quest_bonus_points"
    ]


def _resets(calls):
    return [
        i for i, (name, args, _kw) in enumerate(calls)
        if name == "execute" and RESET_TO_NULL.match(str(args[0]))
    ]


def test_revision_chain():
    mod = _load()
    assert mod.revision == "weekly_quests"
    assert mod.down_revision == "user_badges"


def test_the_bonus_column_is_nullable_with_a_default_of_twenty():
    adds = _bonus_column_adds(_upgrade_calls())
    assert len(adds) == 1
    column = adds[0][1][1]
    assert column.nullable is True
    assert str(column.server_default.arg) == "20"


def test_existing_families_are_reset_to_undecided_exactly_once():
    assert len(_resets(_upgrade_calls())) == 1


def test_the_reset_runs_after_the_column_is_added():
    calls = _upgrade_calls()
    (add_index, _args), = _bonus_column_adds(calls)
    (reset_index,) = _resets(calls)
    assert add_index < reset_index
