"""Idempotency marker for the chore-paycheck payday reminder.

Revision ID: paycheck_reminder_week
Revises: kid_allowance_mode
"""
import sqlalchemy as sa
from alembic import op

revision = "paycheck_reminder_week"
down_revision = "kid_allowance_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kid_bank_accounts",
        sa.Column("last_paycheck_reminder_week", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kid_bank_accounts", "last_paycheck_reminder_week")
