"""calendar_events.recurrence_rule + recurrence_parent_id (W9.2)

Revision ID: cal_rec_v1
Revises: frankie_sch_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "cal_rec_v1"
down_revision = "frankie_sch_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column("recurrence_rule", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "calendar_events",
        sa.Column(
            "recurrence_parent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("calendar_events", "recurrence_parent_id")
    op.drop_column("calendar_events", "recurrence_rule")
