"""mystery_surprises + mystery_boxes + families.mystery_box_points (UX-D4b)

Revision ID: mystery_box
Revises: teen_checkins
Create Date: 2026-10-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "mystery_box"
down_revision = "teen_checkins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("mystery_box_points", sa.Integer(), nullable=True, server_default="20"),
    )
    # Families that already exist start UNDECIDED (NULL = boxes off + a
    # one-time opt-in card on the parent hub). Only families created after
    # this migration get the default of 20 (the quest's opt-in trick).
    op.execute("UPDATE families SET mystery_box_points = NULL")
    op.create_table(
        "mystery_surprises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(60), nullable=False),
        sa.Column("emoji", sa.String(4), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mystery_surprises_family_id", "mystery_surprises", ["family_id"])
    op.create_table(
        "mystery_boxes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("surprise_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mystery_surprises.id", ondelete="SET NULL"), nullable=True),
        sa.Column("surprise_title", sa.String(60), nullable=True),
        sa.Column("surprise_emoji", sa.String(4), nullable=True),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "user_id", "day", name="uq_mystery_boxes_family_user_day"),
        sa.CheckConstraint("kind IS NULL OR kind IN ('surprise','points')", name="ck_mystery_boxes_kind"),
        sa.CheckConstraint("(opened_at IS NULL) = (kind IS NULL)", name="ck_mystery_boxes_opened_iff_kind"),
        sa.CheckConstraint("points >= 0", name="ck_mystery_boxes_points"),
    )
    op.create_index("ix_mystery_boxes_family_id", "mystery_boxes", ["family_id"])
    op.create_index("ix_mystery_boxes_user_id", "mystery_boxes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mystery_boxes_user_id", table_name="mystery_boxes")
    op.drop_index("ix_mystery_boxes_family_id", table_name="mystery_boxes")
    op.drop_table("mystery_boxes")
    op.drop_index("ix_mystery_surprises_family_id", table_name="mystery_surprises")
    op.drop_table("mystery_surprises")
    op.drop_column("families", "mystery_box_points")
