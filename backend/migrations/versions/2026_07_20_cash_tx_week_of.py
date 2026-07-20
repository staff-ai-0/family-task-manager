"""cash_transactions.week_of — the Monday of the chore-paycheck week a
credit belongs to (payout history). Nullable, no backfill: historical rows
predate this and have no reliably machine-parseable week.

Revision ID: cash_tx_week_of
Revises: enabled_modules
"""
import sqlalchemy as sa
from alembic import op

revision = "cash_tx_week_of"
down_revision = "enabled_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cash_transactions", sa.Column("week_of", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("cash_transactions", "week_of")
