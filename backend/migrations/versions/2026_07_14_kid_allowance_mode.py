"""Kid Family-Bank allowance mode (flat vs chore-proportional).

Revision ID: kid_allowance_mode
Revises: family_rest_days
"""
import sqlalchemy as sa
from alembic import op

revision = "kid_allowance_mode"
down_revision = "family_rest_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kid_bank_accounts",
        sa.Column(
            "allowance_mode",
            sa.String(length=20),
            nullable=False,
            server_default="flat",
        ),
    )
    op.add_column(
        "kid_bank_accounts",
        sa.Column("last_chore_paycheck_week", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("kid_bank_accounts", "last_chore_paycheck_week")
    op.drop_column("kid_bank_accounts", "allowance_mode")
