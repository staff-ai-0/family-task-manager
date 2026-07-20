"""Per-family module registry (enabled_modules JSONB, NULL = all on).

Revision ID: enabled_modules
Revises: point_value_cents
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "enabled_modules"
down_revision = "point_value_cents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("families", sa.Column("enabled_modules", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("families", "enabled_modules")
