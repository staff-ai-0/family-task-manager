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


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO plan_credit_grants
            (id, family_id, source, coupon_id, tier, starts_at, ends_at,
             revoked_at, granted_by_user_id, reason, created_at)
        SELECT gen_random_uuid(), f.id, 'referral', NULL, 'plus',
               now(), f.referral_bonus_until, NULL, NULL,
               'backfilled from families.referral_bonus_until', now()
        FROM families f
        WHERE f.referral_bonus_until IS NOT NULL
          AND f.referral_bonus_until > now()
        """
    )
    op.drop_column("families", "referral_bonus_until")


def downgrade() -> None:
    op.add_column(
        "families",
        sa.Column("referral_bonus_until", sa.DateTime(timezone=True), nullable=True),
    )
    # Re-derive from the latest active Plus-or-better credit so a downgrade
    # does not silently strip a family's entitlement. "Plus-or-better"
    # deliberately includes Pro grants: any active tier's MAX(ends_at) is
    # used, because the old column could only ever mean "floored at Plus,
    # until this timestamp" — it had no tier of its own. A family whose only
    # active credit is a Pro grant therefore collapses to a Plus-only
    # timestamp here; that is inherent lossy-ness of the old shape, the same
    # kind of loss lifetime grants (ends_at IS NULL) take below, just for a
    # different reason (missing tier field instead of missing "forever").
    # Lifetime grants (ends_at IS NULL) cannot be represented by a timestamp
    # at all — they are skipped, and that data loss is inherent to going back
    # to the old shape.
    op.execute(
        """
        UPDATE families f
        SET referral_bonus_until = sub.max_end
        FROM (
            SELECT family_id, MAX(ends_at) AS max_end
            FROM plan_credit_grants
            WHERE revoked_at IS NULL
              AND ends_at IS NOT NULL
              AND ends_at > now()
            GROUP BY family_id
        ) sub
        WHERE f.id = sub.family_id
        """
    )
