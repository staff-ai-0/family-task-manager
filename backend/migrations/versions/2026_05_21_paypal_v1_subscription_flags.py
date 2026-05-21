"""add paypal v1 subscription flags

Revision ID: paypal_v1_flags
Revises: a1c4d5e6f7b9
Create Date: 2026-05-21 18:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "paypal_v1_flags"
down_revision = "a1c4d5e6f7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "family_subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "family_subscriptions",
        sa.Column("trial_end_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "family_subscriptions",
        sa.Column(
            "payment_failure_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("family_subscriptions", "payment_failure_at")
    op.drop_column("family_subscriptions", "trial_end_at")
    op.drop_column("family_subscriptions", "cancel_at_period_end")
