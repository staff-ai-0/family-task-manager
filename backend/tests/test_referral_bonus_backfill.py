"""The referral_bonus_until -> plan_credit_grants backfill, against real rows.

This is the ONE place existing production entitlement moves, and until now
nothing executed it with data in the tables: conftest builds the test schema
with ``Base.metadata.create_all``, not alembic, so ``alembic upgrade`` never
runs under pytest, and CI's migration job only round-trips an EMPTY schema.
An INSERT ... SELECT that silently matched zero rows would have passed both.

So the tests below import the migration module by path and execute its
``BACKFILL_SQL`` / ``REDERIVE_SQL`` constants verbatim — the exact strings
``upgrade()`` and ``downgrade()`` hand to ``op.execute``, so the SQL under
test cannot drift from the SQL that ships.

What is NOT covered here, honestly: the DDL legs (``drop_column`` /
``add_column``, their lock_timeout guards) and alembic's own revision
plumbing. Those need a real alembic run against a real schema, which is CI's
migration job. The column is recreated by hand below precisely because the
model no longer has it.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models.family import Family
from app.models.plan_credit import PlanCreditGrant

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "2026_08_02_migrate_referral_bonus_to_grants.py"
)


def _load_migration():
    """Import the revision module by path — its filename starts with a digit,
    so it is not importable as a normal module name."""
    spec = importlib.util.spec_from_file_location("_referral_backfill", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


@pytest_asyncio.fixture
async def legacy_column(db_session):
    """Recreate the dropped column for the duration of one test.

    The schema is session-scoped, so this must be undone or it leaks into
    every later test in the run.
    """
    await db_session.execute(
        text(
            "ALTER TABLE families "
            "ADD COLUMN IF NOT EXISTS referral_bonus_until timestamptz"
        )
    )
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(
        text("ALTER TABLE families DROP COLUMN IF EXISTS referral_bonus_until")
    )
    await db_session.commit()


async def _family(db_session, name: str, bonus_until):
    family = Family(name=name)
    db_session.add(family)
    await db_session.flush()
    await db_session.execute(
        text("UPDATE families SET referral_bonus_until = :b WHERE id = :i"),
        {"b": bonus_until, "i": family.id},
    )
    await db_session.commit()
    return family


async def _grants(db_session, family_id):
    from sqlalchemy import select

    return (
        await db_session.execute(
            select(PlanCreditGrant)
            .where(PlanCreditGrant.family_id == family_id)
            .order_by(PlanCreditGrant.created_at)
        )
    ).scalars().all()


# ---------------------------------------------------------------------------
# upgrade(): the backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_future_bonus_becomes_one_plus_grant(db_session, legacy_column):
    """The whole point of the migration: a family entitled tomorrow under the
    old column is still entitled tomorrow under the new one."""
    ends = datetime.now(timezone.utc) + timedelta(days=20)
    family = await _family(db_session, "Entitled", ends)

    before = datetime.now(timezone.utc)
    await db_session.execute(text(migration.BACKFILL_SQL))
    await db_session.commit()

    grants = await _grants(db_session, family.id)
    assert len(grants) == 1
    g = grants[0]
    assert g.source == "referral"
    assert g.tier == "plus"
    assert g.coupon_id is None
    assert g.revoked_at is None
    # Window: opens now, closes exactly where the old column said.
    assert before <= g.starts_at.replace(tzinfo=timezone.utc) < before + timedelta(
        minutes=1
    )
    assert abs(g.ends_at.replace(tzinfo=timezone.utc) - ends) < timedelta(seconds=1)


@pytest.mark.asyncio
async def test_a_past_or_absent_bonus_grants_nothing(db_session, legacy_column):
    """A lapsed timestamp entitles nobody today; inventing a historical window
    would fabricate an audit trail for credit already consumed."""
    lapsed = await _family(
        db_session, "Lapsed", datetime.now(timezone.utc) - timedelta(days=1)
    )
    never = await _family(db_session, "Never", None)

    await db_session.execute(text(migration.BACKFILL_SQL))
    await db_session.commit()

    assert await _grants(db_session, lapsed.id) == []
    assert await _grants(db_session, never.id) == []


@pytest.mark.asyncio
async def test_re_running_the_backfill_fabricates_nothing(
    db_session, legacy_column
):
    """upgrade -> downgrade -> upgrade is the documented deploy recovery, and
    the downgrade re-derives the column WITHOUT revoking the grants it read.
    A second upgrade must therefore be a no-op for already-covered families.

    Without the NOT EXISTS guard this inserts a second 'referral' grant beside
    the live original — and UNIQUE(family_id, coupon_id) cannot catch it,
    because coupon_id is NULL on both and Postgres treats NULLs as distinct.
    """
    ends = datetime.now(timezone.utc) + timedelta(days=20)
    family = await _family(db_session, "Redeployed", ends)

    await db_session.execute(text(migration.BACKFILL_SQL))
    await db_session.commit()
    assert len(await _grants(db_session, family.id)) == 1

    # The downgrade leg puts the value back on the column, unchanged...
    await db_session.execute(text(migration.REDERIVE_SQL))
    await db_session.commit()
    # ...and the redeploy runs upgrade again.
    await db_session.execute(text(migration.BACKFILL_SQL))
    await db_session.commit()

    assert len(await _grants(db_session, family.id)) == 1, (
        "the second upgrade fabricated a duplicate grant; revoking the "
        "original would silently leave the family entitled"
    )


@pytest.mark.asyncio
async def test_a_revoked_grant_does_not_suppress_the_backfill(
    db_session, legacy_column
):
    """The guard keys on LIVE coverage. A revoked grant covers nothing, so a
    family still holding a future column value must be backfilled — otherwise
    the guard would quietly strip entitlement instead of protecting it."""
    ends = datetime.now(timezone.utc) + timedelta(days=20)
    family = await _family(db_session, "Revoked", ends)
    now = datetime.now(timezone.utc)
    db_session.add(
        PlanCreditGrant(
            family_id=family.id,
            source="operator",
            tier="plus",
            starts_at=now,
            ends_at=ends,
            revoked_at=now,
        )
    )
    await db_session.commit()

    await db_session.execute(text(migration.BACKFILL_SQL))
    await db_session.commit()

    live = [g for g in await _grants(db_session, family.id) if g.revoked_at is None]
    assert len(live) == 1
    assert live[0].source == "referral"


# ---------------------------------------------------------------------------
# downgrade(): the re-derive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_lifetime_grant_survives_the_down_leg_as_infinity(
    db_session, legacy_column
):
    """A lifetime comp must NOT be silently downgraded to free by a rollback.

    'infinity'::timestamptz represents it exactly under the old shape, whose
    only consumer was `bonus_until > now()`.
    """
    family = await _family(db_session, "Forever", None)
    db_session.add(
        PlanCreditGrant(
            family_id=family.id,
            source="operator",
            tier="pro",
            starts_at=datetime.now(timezone.utc) - timedelta(days=1),
            ends_at=None,
        )
    )
    await db_session.commit()

    await db_session.execute(text(migration.REDERIVE_SQL))
    await db_session.commit()

    still_entitled = (
        await db_session.execute(
            text(
                "SELECT referral_bonus_until > now() FROM families WHERE id = :i"
            ),
            {"i": family.id},
        )
    ).scalar_one()
    assert still_entitled is True, "the lifetime grant was dropped to free"


@pytest.mark.asyncio
async def test_the_down_leg_ignores_revoked_and_queued_grants(
    db_session, legacy_column
):
    """Neither a revoked credit nor one whose window has not opened entitles
    anybody today, and the old column had no way to say "not yet"."""
    now = datetime.now(timezone.utc)
    revoked = await _family(db_session, "Revoked", None)
    queued = await _family(db_session, "Queued", None)
    db_session.add_all(
        [
            PlanCreditGrant(
                family_id=revoked.id,
                source="operator",
                tier="plus",
                starts_at=now - timedelta(days=1),
                ends_at=now + timedelta(days=30),
                revoked_at=now,
            ),
            PlanCreditGrant(
                family_id=queued.id,
                source="operator",
                tier="plus",
                starts_at=now + timedelta(days=10),
                ends_at=now + timedelta(days=40),
            ),
        ]
    )
    await db_session.commit()

    await db_session.execute(text(migration.REDERIVE_SQL))
    await db_session.commit()

    values = (
        await db_session.execute(
            text(
                "SELECT referral_bonus_until FROM families WHERE id = ANY(:ids)"
            ),
            {"ids": [revoked.id, queued.id]},
        )
    ).scalars().all()
    assert values == [None, None]
