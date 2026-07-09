"""Kid savings goals + Star Mode (P2)

Adds, in ONE revision:
  1. kid_savings_goals — a kid's single named CASH savings goal tracked against
     the Family Bank Save jar. Lives entirely on the cash currency; no reward_id
     / no points coupling (see UserRewardGoal for the separate points goal).
     Partial-unique index over user_id WHERE status IN ('pending','active')
     enforces the v1 "one active goal per kid" rule.
  2. users.star_mode — BOOLEAN NOT NULL DEFAULT false. Per-kid "young kid"
     display toggle (parent-set): render POINTS as big stars + hide peso amounts
     on the kid dashboard + kiosk. Pure presentation over the existing points
     system; not a currency. Instant on PG15 (non-volatile default), no backfill.

Downgrade drops the table + column.

Revision ID: savings_goal_star_mode
Revises: family_bank_w1
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "savings_goal_star_mode"
down_revision = "family_bank_w1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Per-kid named cash savings goal (Save jar).
    op.create_table(
        "kid_savings_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("emoji", sa.String(8), nullable=True),
        sa.Column("target_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("reached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "target_cents > 0", name="ck_kid_savings_goal_target_positive"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'cancelled')",
            name="ck_kid_savings_goal_status",
        ),
    )
    op.create_index(
        "ix_kid_savings_goals_family_id", "kid_savings_goals", ["family_id"]
    )
    # v1: at most one pending-or-active goal per kid.
    op.create_index(
        "ix_kid_savings_goals_active",
        "kid_savings_goals",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'active')"),
    )

    # 2. Star Mode display toggle on users.
    op.add_column(
        "users",
        sa.Column(
            "star_mode", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "star_mode")
    op.drop_index("ix_kid_savings_goals_active", table_name="kid_savings_goals")
    op.drop_index("ix_kid_savings_goals_family_id", table_name="kid_savings_goals")
    op.drop_table("kid_savings_goals")
