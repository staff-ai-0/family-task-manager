"""users.last_seen_rank for the UX-D1 rank-up celebration

Revision ID: user_last_seen_rank
Revises: mark_stale_reminders_read
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = "user_last_seen_rank"
down_revision = "mark_stale_reminders_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_rank", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen_rank")
