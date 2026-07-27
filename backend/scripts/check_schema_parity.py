#!/usr/bin/env python
"""Fail if the migration-derived schema and the ORM-derived schema disagree.

Why this exists
---------------
CI runs `alembic upgrade head`, but backend/tests/conftest.py then drops every
table and rebuilds the schema with ``Base.metadata.create_all``.  The entire
pytest suite therefore runs against the ORM-derived schema and *never* against
the one production actually has.  Anything the migrations enforce but the models
do not (CHECK constraints, unique constraints, FK ondelete) is invisible to CI.

`alembic check` is NOT sufficient on its own: alembic's autogenerate comparison
does not diff CHECK constraints at all, which is exactly where this repo's real
drift lives.  It also reports ~160 cosmetic diffs (server_default / index-name /
comment noise) that would make it permanently red.

Usage
-----
    DATABASE_URL=<url of a DB already at `alembic upgrade head`> \
    ORM_DATABASE_URL=<url of a scratch DB this script will (re)create> \
    python scripts/check_schema_parity.py

Both URLs may carry the ``+asyncpg`` driver tag; it is stripped, because
reflection and ``create_all`` here run on a **sync** psycopg2 engine.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text  # noqa: E402

import app.models  # noqa: F401,E402  — side effect: populates Base.metadata
from app.core.database import Base  # noqa: E402


def sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


MIG_URL = sync_url(os.environ["DATABASE_URL"])
ORM_URL = sync_url(os.environ.get("ORM_DATABASE_URL") or MIG_URL + "_ormparity")


def recreate_orm_db() -> None:
    """CREATE DATABASE cannot run inside a transaction -> AUTOCOMMIT."""
    admin_url = ORM_URL.rsplit("/", 1)[0] + "/postgres"
    dbname = ORM_URL.rsplit("/", 1)[1]
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :d AND pid <> pg_backend_pid()"), {"d": dbname})
        c.execute(text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        c.execute(text(f'CREATE DATABASE "{dbname}"'))
    eng.dispose()
    orm_eng = create_engine(ORM_URL)
    Base.metadata.create_all(orm_eng)
    orm_eng.dispose()


# --- the comparisons that matter -------------------------------------------
# Deliberately EXCLUDED as non-semantic: index *names*, column comments,
# server_default text, and physical column order.

Q = {
    "tables": """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
          AND table_name <> 'alembic_version'
    """,
    "columns": """
        SELECT table_name||'.'||column_name||' :: '||udt_name
               ||' :: nullable='||is_nullable
               ||' :: len='||coalesce(character_maximum_length::text,'-')
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name <> 'alembic_version'
    """,
    "check_constraints": """
        SELECT c.conrelid::regclass::text||' :: '||c.conname
               ||' :: '||pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        WHERE n.nspname='public' AND c.contype='c'
    """,
    "foreign_keys": """
        SELECT c.conrelid::regclass::text||' :: '||pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        WHERE n.nspname='public' AND c.contype='f'
    """,
    # Uniqueness by DEFINITION, not by name: a UNIQUE CONSTRAINT and a UNIQUE
    # INDEX on the same columns are equivalent enforcement, so compare the
    # column tuple + predicate only.
    # Uniqueness by DEFINITION, not by name: a UNIQUE CONSTRAINT and a UNIQUE
    # INDEX on the same columns enforce the same rule, and this repo genuinely
    # uses both spellings. Strip the index name, keep columns + predicate.
    "unique_enforcement": """
        SELECT regexp_replace(pg_get_indexdef(ix.indexrelid),
                              'INDEX [^ ]+ ON', 'INDEX ON')
        FROM pg_index ix
        JOIN pg_class c  ON c.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname='public' AND ix.indisunique AND NOT ix.indisprimary
          AND c.relname <> 'alembic_version'
    """,
    "enum_labels": """
        SELECT t.typname||' = '||string_agg(e.enumlabel, ',' ORDER BY e.enumlabel)
        FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid
        JOIN pg_namespace n ON n.oid=t.typnamespace
        WHERE n.nspname='public' GROUP BY t.typname
    """,
    "primary_keys": """
        SELECT c.conrelid::regclass::text||' :: '||pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
        WHERE n.nspname='public' AND c.contype='p'
          AND c.conrelid::regclass::text <> 'alembic_version'
    """,
}


def snapshot(url: str) -> dict[str, set[str]]:
    eng = create_engine(url)
    out: dict[str, set[str]] = {}
    with eng.connect() as c:
        for key, q in Q.items():
            out[key] = {r[0] for r in c.execute(text(q)) if r[0] is not None}
    eng.dispose()
    return out


def main() -> int:
    recreate_orm_db()
    mig = snapshot(MIG_URL)
    orm = snapshot(ORM_URL)

    problems: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for key in Q:
        only_mig = sorted(mig[key] - orm[key])
        only_orm = sorted(orm[key] - mig[key])
        if only_mig:
            problems[key]["in MIGRATIONS (prod) but NOT in models (tests)"] = only_mig
        if only_orm:
            problems[key]["in models (tests) but NOT in MIGRATIONS (prod)"] = only_orm

    if not problems:
        print("schema parity OK — migration-derived and ORM-derived schemas agree")
        return 0

    print("SCHEMA PARITY FAILURE\n" + "=" * 70)
    for key, sides in problems.items():
        print(f"\n## {key}")
        for side, items in sides.items():
            print(f"  {side}:")
            for i in items:
                print(f"    - {i}")
    print("\n" + "=" * 70)
    print("Fix by mirroring the migration DDL into the model's __table_args__ "
          "(or adding a migration for the model-only object).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
