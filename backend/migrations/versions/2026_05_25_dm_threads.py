"""dm_threads + dm_messages tables (W9.3)

Revision ID: dm_v1
Revises: cal_rec_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "dm_v1"
down_revision = "cal_rec_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dm_threads",
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
        sa.Column("participant_ids", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_dm_threads_family", "dm_threads", ["family_id"])

    op.create_table(
        "dm_messages",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "thread_id",
            UUID(as_uuid=True),
            sa.ForeignKey("dm_threads.id", ondelete="CASCADE"),
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
    op.create_index("ix_dm_msg_thread_created", "dm_messages", ["thread_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_dm_msg_thread_created", table_name="dm_messages")
    op.drop_table("dm_messages")
    op.drop_index("ix_dm_threads_family", table_name="dm_threads")
    op.drop_table("dm_threads")
