"""early_bird_past_periods — keep closed on-periods across an off->on toggle

Revision ID: early_bird_past_periods
Revises: early_bird
Create Date: 2026-11-12

`families.early_bird_enabled_at` is re-stamped on every off->on, and week
eligibility compared every week against it, so switching the feature off and
on again voided weeks a teen had already earned (paycheck +% and streak). The
closed periods are now kept in `early_bird_past_periods` (JSONB, NULL = none).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "early_bird_past_periods"
down_revision = "early_bird"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("early_bird_past_periods", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("families", "early_bird_past_periods")
