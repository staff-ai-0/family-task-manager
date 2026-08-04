"""Backfill families.referral_bonus_until into plan_credit_grants, drop it.

The column was a single Plus-only timestamp shared by the referral program
and the operator comp action. plan_credit_grants supersedes it with per-grant
tier, lifetime support, revocation and an audit trail.

Backfill scope: only FUTURE values become grants. A past timestamp entitles
nobody today, and inventing a historical window would fabricate an audit
trail for credit that has already been consumed.

Revision ID: migrate_referral_bonus_to_grants
Revises: plan_credit_tables
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = "migrate_referral_bonus_to_grants"
down_revision = "plan_credit_tables"
branch_labels = None
depends_on = None


# The two data statements live as module constants so tests can execute the
# EXACT production string against seeded rows. conftest builds the test schema
# with Base.metadata.create_all rather than alembic, so `alembic upgrade` never
# runs under pytest and the backfill — the one place existing production
# entitlement moves — would otherwise be exercised by nothing but an
# empty-schema round-trip in CI. See tests/test_referral_bonus_backfill.py.
BACKFILL_SQL = """
        INSERT INTO plan_credit_grants
            (id, family_id, source, coupon_id, tier, starts_at, ends_at,
             revoked_at, granted_by_user_id, reason, created_at)
        SELECT gen_random_uuid(), f.id, 'referral', NULL, 'plus',
               now(), f.referral_bonus_until, NULL, NULL,
               'backfilled from families.referral_bonus_until', now()
        FROM families f
        WHERE f.referral_bonus_until IS NOT NULL
          AND f.referral_bonus_until > now()
          -- Idempotence guard. downgrade-then-redeploy is the documented
          -- deploy recovery, and the downgrade re-derives this column from
          -- grants it deliberately does NOT revoke. Without this, a second
          -- upgrade inserts a fresh 'referral' grant BESIDE the still-live
          -- original and the family silently holds two.
          -- UNIQUE(family_id, coupon_id) cannot stop it: coupon_id is NULL
          -- here and Postgres treats NULLs as distinct. Entitlement looks
          -- unchanged while both are live, so the fabrication only surfaces
          -- later — when an operator revokes the original and the phantom
          -- quietly keeps the family entitled.
          --
          -- On a genuine first upgrade plan_credit_grants was just created
          -- empty by the preceding revision, so this is vacuously true and
          -- the backfill behaves exactly as before.
          AND NOT EXISTS (
              SELECT 1 FROM plan_credit_grants g
              WHERE g.family_id = f.id
                AND g.revoked_at IS NULL
                AND g.starts_at <= now()
                AND COALESCE(g.ends_at, 'infinity'::timestamptz)
                    >= f.referral_bonus_until
          )
"""

REDERIVE_SQL = """
        UPDATE families f
        SET referral_bonus_until = sub.max_end
        FROM (
            SELECT family_id,
                   MAX(COALESCE(ends_at, 'infinity'::timestamptz)) AS max_end
            FROM plan_credit_grants
            WHERE revoked_at IS NULL
              AND COALESCE(ends_at, 'infinity'::timestamptz) > now()
              -- Queued grants excluded: the old column meant "entitled
              -- until", with no notion of a window that has not opened,
              -- so counting one would hand back entitlement the family
              -- does not have yet.
              AND starts_at <= now()
            GROUP BY family_id
        ) sub
        WHERE f.id = sub.family_id
"""


def upgrade() -> None:
    op.execute(BACKFILL_SQL)
    # DROP COLUMN takes ACCESS EXCLUSIVE on `families` while the OLD backend
    # is still serving, and get_current_user joins `families` on every
    # authenticated request — the moment this ALTER starts waiting, all of
    # them queue behind it and the whole site stalls for as long as the
    # deploy does. Fail the deploy fast instead; a stuck migration is
    # recoverable, a silently wedged site during a deploy window is not.
    #
    # SET LOCAL, not SET: env.py wraps the entire `alembic upgrade` run in
    # ONE transaction (a single context.begin_transaction()), so a plain SET
    # would leak this timeout into every later revision of the same run.
    # Reset immediately after for the same reason.
    #
    # Only this statement needs it. The backfill above takes ACCESS SHARE on
    # `families` — which does not conflict with the SELECTs the old backend
    # is issuing — plus ROW EXCLUSIVE on the brand-new, traffic-free
    # plan_credit_grants, so it cannot be the statement that blocks.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("families", "referral_bonus_until")
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
    # Same ACCESS EXCLUSIVE reasoning as the drop in upgrade(): this runs
    # during a rollback, with the NEW backend still serving and joining
    # `families` on every authenticated request.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "families",
        sa.Column("referral_bonus_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("SET LOCAL lock_timeout = DEFAULT")
    # Re-derive from the latest active Plus-or-better credit so a downgrade
    # does not silently strip a family's entitlement. "Plus-or-better"
    # deliberately includes Pro grants: any active tier's MAX(ends_at) is
    # used, because the old column could only ever mean "floored at Plus,
    # until this timestamp" — it had no tier of its own. A family whose only
    # active credit is a Pro grant therefore collapses to a Plus-only
    # timestamp here; that tier loss IS inherent to the old shape, which has
    # nowhere to put a tier.
    #
    # Lifetime grants are NOT inherently lossy, and are no longer dropped.
    # An earlier version of this migration skipped them on the claim that a
    # timestamp "cannot" represent "forever" — it can:
    # COALESCE(ends_at, 'infinity'::timestamptz). The old column's only
    # consumer was `bonus_until > now()` (premium.get_family_plan_by_id
    # before this branch removed it), and infinity satisfies that forever,
    # which is exactly right. asyncpg round-trips it as a naive
    # datetime.max, and that consumer coerced naive values to UTC before
    # comparing, so it reads correctly on both sides of the driver. Skipping
    # them instead silently dropped a lifetime comp to free — a far worse
    # outcome than the tier collapse above, and unlike it, avoidable.
    op.execute(REDERIVE_SQL)
