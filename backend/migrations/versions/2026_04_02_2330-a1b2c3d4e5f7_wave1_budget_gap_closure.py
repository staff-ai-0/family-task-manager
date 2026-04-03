"""wave1 budget gap closure: favorite payees, schedule end modes

Revision ID: a1b2c3d4e5f7
Revises: 586649b5ef22
Create Date: 2026-04-02 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "586649b5ef22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Feature 1: Favorite payees
    op.add_column(
        "budget_payees",
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Feature 3: Schedule end modes on recurring transactions
    op.add_column(
        "budget_recurring_transactions",
        sa.Column("end_mode", sa.String(20), nullable=False, server_default=sa.text("'never'")),
    )
    op.add_column(
        "budget_recurring_transactions",
        sa.Column("occurrence_limit", sa.Integer(), nullable=True),
    )
    op.add_column(
        "budget_recurring_transactions",
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "budget_recurring_transactions",
        sa.Column("weekend_behavior", sa.String(20), nullable=False, server_default=sa.text("'none'")),
    )


def downgrade() -> None:
    op.drop_column("budget_recurring_transactions", "weekend_behavior")
    op.drop_column("budget_recurring_transactions", "occurrence_count")
    op.drop_column("budget_recurring_transactions", "occurrence_limit")
    op.drop_column("budget_recurring_transactions", "end_mode")
    op.drop_column("budget_payees", "is_favorite")
