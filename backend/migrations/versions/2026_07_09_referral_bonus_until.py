"""Referral credit lives on families.referral_bonus_until

Follow-up to the referral_program migration, resolving a re-review defect: a
paid referrer's give-a-month reward was written to the subscription's
current_period_end and then silently erased within 24h by the nightly PayPal
reconcile sweep (which overwrites current_period_end from PayPal's
next_billing_at — PayPal knows nothing of the internal +30d).

The credit now lives on a dedicated families.referral_bonus_until timestamp
that the reconcile sweep never touches; premium.get_family_plan honors it as
a Plus floor while it is in the future. Applies uniformly to paid AND free
referrers, so the divergent paths that manipulated PayPal linkage are gone.

Additive on PG15: a single nullable timestamp column (no rewrite, no
backfill — NULL means "no credit"). Downgrade drops it.

Revision ID: referral_bonus_until
Revises: referral_program
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op


revision = "referral_bonus_until"
down_revision = "referral_program"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column(
            "referral_bonus_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("families", "referral_bonus_until")
