"""family_chat_messages table (W8.1)

Revision ID: fchat_v1
Revises: meals_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "fchat_v1"
down_revision = "meals_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "family_chat_messages",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sender_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_family_chat_family_created",
        "family_chat_messages",
        ["family_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_family_chat_family_created", table_name="family_chat_messages"
    )
    op.drop_table("family_chat_messages")
