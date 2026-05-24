"""frankie_messages table (W6.1)

Revision ID: frankie_v1
Revises: pet_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "frankie_v1"
down_revision = "pet_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frankie_messages",
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
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_frankie_family_created",
        "frankie_messages",
        ["family_id", "created_at"],
    )
    op.create_check_constraint(
        "chk_frankie_role",
        "frankie_messages",
        "role IN ('user', 'assistant', 'system')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_frankie_role", "frankie_messages", type_="check")
    op.drop_index("ix_frankie_family_created", table_name="frankie_messages")
    op.drop_table("frankie_messages")
