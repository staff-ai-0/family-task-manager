"""family_subscriptions stripe fields (W9.4)

Revision ID: stripe_v1
Revises: dm_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "stripe_v1"
down_revision = "dm_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "family_subscriptions",
        sa.Column("stripe_customer_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "family_subscriptions",
        sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_fsub_stripe_sub",
        "family_subscriptions",
        ["stripe_subscription_id"],
        unique=True,
        postgresql_where=sa.text("stripe_subscription_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_fsub_stripe_sub", table_name="family_subscriptions")
    op.drop_column("family_subscriptions", "stripe_subscription_id")
    op.drop_column("family_subscriptions", "stripe_customer_id")
