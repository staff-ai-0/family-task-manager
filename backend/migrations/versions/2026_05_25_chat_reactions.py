"""family_chat_reactions table (W8.6)

Revision ID: chat_react_v1
Revises: chat_read_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "chat_react_v1"
down_revision = "chat_read_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "family_chat_reactions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("family_chat_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "message_id", "user_id", "emoji", name="uq_chat_react_unique"
        ),
    )
    op.create_index(
        "ix_chat_react_message", "family_chat_reactions", ["message_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_react_message", table_name="family_chat_reactions")
    op.drop_table("family_chat_reactions")
