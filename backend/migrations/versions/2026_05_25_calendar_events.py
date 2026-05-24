"""calendar_events table (W2.1)

Revision ID: cal_evt_v1
Revises: shop_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "cal_evt_v1"
down_revision = "shop_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
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
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "all_day", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("attendees", JSONB(), nullable=True),
        sa.Column("color", sa.String(length=24), nullable=True),
        sa.Column(
            "source", sa.String(length=24), nullable=False, server_default="manual"
        ),
        sa.Column("source_doc_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        "ix_calendar_events_family_start",
        "calendar_events",
        ["family_id", "start_ts"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendar_events_family_start", table_name="calendar_events"
    )
    op.drop_table("calendar_events")
