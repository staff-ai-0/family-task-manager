"""kiosk_devices table (W3.3)

Revision ID: kiosk_v1
Revises: notif_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "kiosk_v1"
down_revision = "notif_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiosk_devices",
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
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False, unique=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index("ix_kiosk_devices_family", "kiosk_devices", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_kiosk_devices_family", table_name="kiosk_devices")
    op.drop_table("kiosk_devices")
