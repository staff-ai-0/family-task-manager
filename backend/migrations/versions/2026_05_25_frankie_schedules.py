"""frankie_schedules table (W9.1)

Revision ID: frankie_sch_v1
Revises: chat_react_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "frankie_sch_v1"
down_revision = "chat_react_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frankie_schedules",
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
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("cron_expr", sa.String(length=64), nullable=False),
        sa.Column(
            "channel", sa.String(length=16), nullable=False, server_default="notification"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_frankie_sched_active_next",
        "frankie_schedules",
        ["is_active", "next_run_at"],
    )
    op.create_check_constraint(
        "chk_frankie_channel",
        "frankie_schedules",
        "channel IN ('notification', 'chat')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_frankie_channel", "frankie_schedules", type_="check")
    op.drop_index("ix_frankie_sched_active_next", table_name="frankie_schedules")
    op.drop_table("frankie_schedules")
