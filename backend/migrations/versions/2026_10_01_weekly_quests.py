"""weekly_quests + families.quest_bonus_points for UX-D3

Revision ID: weekly_quests
Revises: user_badges
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "weekly_quests"
down_revision = "user_badges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("quest_bonus_points", sa.Integer(), nullable=True, server_default="20"),
    )
    # Families that already exist start UNDECIDED (NULL = quests off + a
    # one-time opt-in card on the parent hub). Only families created after
    # this migration get the default of 20.
    op.execute("UPDATE families SET quest_bonus_points = NULL")
    op.create_table(
        "weekly_quests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("quest", sa.String(32), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("bonus_points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("family_id", "user_id", "week_start", name="uq_weekly_quests_family_user_week"),
        sa.CheckConstraint("target >= 1", name="ck_weekly_quests_target"),
        sa.CheckConstraint("bonus_points >= 0", name="ck_weekly_quests_bonus"),
    )
    op.create_index("ix_weekly_quests_family_id", "weekly_quests", ["family_id"])
    op.create_index("ix_weekly_quests_user_id", "weekly_quests", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_weekly_quests_user_id", table_name="weekly_quests")
    op.drop_index("ix_weekly_quests_family_id", table_name="weekly_quests")
    op.drop_table("weekly_quests")
    op.drop_column("families", "quest_bonus_points")
