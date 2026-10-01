"""user_badges for UX-D2 badges (earned tiers, permanent)

Revision ID: user_badges
Revises: user_last_seen_rank
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "user_badges"
down_revision = "user_last_seen_rank"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_badges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("badge", sa.String(32), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "family_id", "user_id", "badge", "tier", name="uq_user_badges_family_user_badge_tier",
        ),
        sa.CheckConstraint("tier BETWEEN 1 AND 3", name="ck_user_badges_tier"),
    )
    op.create_index("ix_user_badges_family_id", "user_badges", ["family_id"])
    op.create_index("ix_user_badges_user_id", "user_badges", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_badges_user_id", table_name="user_badges")
    op.drop_index("ix_user_badges_family_id", table_name="user_badges")
    op.drop_table("user_badges")
