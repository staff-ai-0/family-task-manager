"""users.chat_last_read_at (W8.5)

Revision ID: chat_read_v1
Revises: fchat_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "chat_read_v1"
down_revision = "fchat_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "chat_last_read_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "chat_last_read_at")
