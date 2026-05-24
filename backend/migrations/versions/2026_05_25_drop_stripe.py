"""drop dead stripe columns + index (W11A cleanup)

User rejected Stripe path. Columns added in stripe_v1 never used.

Revision ID: drop_stripe_v1
Revises: stripe_v1
Create Date: 2026-05-25
"""
from alembic import op


revision = "drop_stripe_v1"
down_revision = "stripe_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Best-effort drops — tolerate missing index/columns on rerun.
    try:
        op.drop_index("ix_fsub_stripe_sub", table_name="family_subscriptions")
    except Exception:
        pass
    try:
        op.drop_column("family_subscriptions", "stripe_subscription_id")
    except Exception:
        pass
    try:
        op.drop_column("family_subscriptions", "stripe_customer_id")
    except Exception:
        pass


def downgrade() -> None:
    # Not restoring — Stripe path is permanently retired.
    pass
