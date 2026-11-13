"""early_bird migration: a real upgrade -> downgrade -> upgrade on a scratch DB.

The suite's schema comes from create_all, so enum ALTERs are only exercised
for real here (and in CI's alembic round-trip job). Skips when no Postgres.
"""
import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone

import asyncpg
import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BASE = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://familyapp:familyapp123@localhost:5435/familyapp_test",
).replace("postgresql+asyncpg://", "postgresql://")
ADMIN_DSN = BASE.rsplit("/", 1)[0] + "/postgres"


def _alembic(dsn: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": dsn}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def _sql(dsn: str, query: str, *params):
    async def run():
        c = await asyncpg.connect(dsn)
        try:
            return await c.fetch(query, *params)
        finally:
            await c.close()
    return asyncio.run(run())


@pytest.fixture
def scratch_dsn():
    name = f"eb_mig_{uuid.uuid4().hex[:8]}"
    try:
        _sql(ADMIN_DSN, f"CREATE DATABASE {name}")
    except Exception as exc:  # no server / no CREATEDB
        pytest.skip(f"cannot create scratch database: {exc}")
    yield BASE.rsplit("/", 1)[0] + "/" + name
    _sql(ADMIN_DSN, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _insert(dsn, table, **given):
    """Insert one row, filling every other NOT NULL column that has no default."""
    cols = _sql(dsn, "SELECT column_name AS n, data_type AS t, udt_name AS u FROM information_schema.columns "
                     "WHERE table_name = $1 AND is_nullable = 'NO' AND column_default IS NULL", table)
    fill = {"text": "x", "character varying": "x", "integer": 0, "bigint": 0, "boolean": False,
            "date": date(2026, 11, 2), "timestamp with time zone": datetime.now(timezone.utc),
            "jsonb": "{}"}
    values = dict(given)
    for c in cols:
        if c["n"] not in values:
            values[c["n"]] = fill[c["t"]]
    names = list(values)
    casts = []
    for i, n in enumerate(names, 1):
        t = next((c["t"] for c in cols if c["n"] == n), None)
        casts.append(f"${i}::jsonb" if t == "jsonb" else f"${i}")
    _sql(dsn, f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(casts)})", *values.values())


def _cols(dsn, table):
    return {r["column_name"] for r in _sql(
        dsn, "SELECT column_name FROM information_schema.columns WHERE table_name = $1", table)}


def _labels(dsn, typ):
    return {r["e"] for r in _sql(
        dsn, "SELECT enumlabel AS e FROM pg_enum JOIN pg_type t ON t.oid = enumtypid WHERE typname = $1", typ)}


def test_round_trip(scratch_dsn):
    dsn = scratch_dsn
    _alembic(dsn, "upgrade", "head")
    assert {"early_bird_enabled", "early_bird_deadline", "early_bird_days",
            "early_bird_past_periods"} <= _cols(dsn, "families")
    assert "early_bird_exempt" in _cols(dsn, "task_templates")
    assert {"taken_by", "taken_at", "taken_from_id", "early_bonus_points"} <= _cols(dsn, "task_assignments")
    assert _cols(dsn, "early_bird_weeks")
    assert "taken" in _labels(dsn, "assignmentstatus")
    assert "BONUS" in _labels(dsn, "cashtransactiontype")

    # rows that use the new values
    fam, usr, tpl = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _insert(dsn, "families", id=fam, name="F")
    assert _sql(dsn, "SELECT early_bird_deadline::text AS d FROM families")[0]["d"] == "11:00:00"
    _insert(dsn, "users", id=usr, email=f"{usr}@x.com", family_id=fam, role="TEEN")
    _insert(dsn, "task_templates", id=tpl, family_id=fam, assignment_type="auto")
    _insert(dsn, "task_assignments", id=uuid.uuid4(), template_id=tpl, assigned_to=usr,
            family_id=fam, status="taken", assigned_date=date(2026, 11, 2), week_of=date(2026, 11, 2))
    _insert(dsn, "cash_transactions", id=uuid.uuid4(), type="BONUS", amount_cents=500,
            user_id=usr, family_id=fam)

    # To the revision before early_bird by name: later Early Bird migrations
    # (early_bird_past_periods) sit on top, so "-1" would stop short.
    _alembic(dsn, "downgrade", "payout_receipts")
    assert not _cols(dsn, "early_bird_weeks")
    assert not ({"early_bird_enabled", "early_bird_past_periods"} & _cols(dsn, "families"))
    assert not ({"taken_by", "early_bonus_points"} & _cols(dsn, "task_assignments"))
    assert "early_bird_exempt" not in _cols(dsn, "task_templates")
    assert "taken" not in _labels(dsn, "assignmentstatus")
    assert "BONUS" not in _labels(dsn, "cashtransactiontype")
    assert _sql(dsn, "SELECT status::text AS s FROM task_assignments")[0]["s"] == "cancelled"
    assert _sql(dsn, "SELECT type::text AS t FROM cash_transactions")[0]["t"] == "ADJUSTMENT"

    _alembic(dsn, "upgrade", "head")
    assert "taken" in _labels(dsn, "assignmentstatus")
    assert "BONUS" in _labels(dsn, "cashtransactiontype")


def test_chore_rules_v2_round_trip(scratch_dsn):
    dsn = scratch_dsn
    _alembic(dsn, "upgrade", "early_bird_past_periods")
    _insert(dsn, "families", id=uuid.uuid4(), name="Old")
    _alembic(dsn, "upgrade", "head")
    new = {"chore_cutoff", "grab_window_end", "teen_alarm_1", "teen_alarm_2", "rules_version"}
    assert new <= _cols(dsn, "families")
    row = _sql(dsn, "SELECT chore_cutoff::text AS c, grab_window_end::text AS g, "
                    "teen_alarm_1::text AS a1, teen_alarm_2::text AS a2, rules_version AS v, "
                    "early_bird_streak_cents AS s FROM families")[0]
    assert (row["c"], row["g"], row["a1"], row["a2"], row["v"]) == (
        "20:30:00", "22:30:00", "15:00:00", "19:00:00", 1)
    assert row["s"] == 50000  # existing family is not rewritten

    _alembic(dsn, "downgrade", "early_bird_past_periods")
    assert not (new & _cols(dsn, "families"))
    _alembic(dsn, "upgrade", "head")
    assert new <= _cols(dsn, "families")
