"""Family rest days — weekdays the shuffle assigns no tasks.

Revision ID: family_rest_days
Revises: budget_hold_notes
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "family_rest_days"
down_revision = "budget_hold_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("rest_days", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("families", "rest_days")
