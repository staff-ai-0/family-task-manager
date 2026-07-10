"""Parent chat moderation: edited_at on family_chat_messages.

Revision ID: chat_moderation
Revises: task_forensic_fixes
"""
import sqlalchemy as sa
from alembic import op

revision = "chat_moderation"
down_revision = "task_forensic_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "family_chat_messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("family_chat_messages", "edited_at")
