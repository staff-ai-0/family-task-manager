"""Routines library: routines + routine_steps + routine_progress

Icon tap-through routines for pre-readers (a family-command-center staple).
Three new tables, in ONE revision chained off the referral head
(referral_bonus_until):

  1. routines          — parent-authored, family-scoped, per-kid or family-wide
                         (assigned_user_id NULL = family). points_reward is the
                         POINTS (privileges — never cash) granted on full
                         completion. time_of_day buckets it (morning/evening/
                         custom). color = optional per-kid kiosk color.

  2. routine_steps     — ordered bilingual step (label + label_es + emoji icon)
                         belonging to a routine (CASCADE on routine delete).

  3. routine_progress  — per (routine, user, local-day) tap state:
                         completed_step_ids (JSONB list) + a one-shot `awarded`
                         guard so the points/pet reward fires exactly once per
                         day. UNIQUE(routine_id, user_id, completion_date).

All-additive on PG15: three brand-new empty tables, no rewrite/backfill of
existing data. Downgrade drops them (child tables first).

Revision ID: routines_library
Revises: referral_bonus_until
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "routines_library"
down_revision = "referral_bonus_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_es", sa.String(length=120), nullable=True),
        sa.Column(
            "icon", sa.String(length=16), nullable=False, server_default="🌅"
        ),
        sa.Column("color", sa.String(length=9), nullable=True),
        sa.Column(
            "time_of_day",
            sa.String(length=16),
            nullable=False,
            server_default="morning",
        ),
        sa.Column(
            "assigned_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "points_reward", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "time_of_day IN ('morning', 'evening', 'custom')",
            name="chk_routine_time_of_day",
        ),
        sa.CheckConstraint(
            "points_reward >= 0", name="chk_routine_points_reward"
        ),
    )
    op.create_index(
        "ix_routines_family_id", "routines", ["family_id"], unique=False
    )
    op.create_index(
        "ix_routines_assigned_user_id",
        "routines",
        ["assigned_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_routines_is_active", "routines", ["is_active"], unique=False
    )

    op.create_table(
        "routine_steps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "routine_id",
            UUID(as_uuid=True),
            sa.ForeignKey("routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("label_es", sa.String(length=120), nullable=True),
        sa.Column(
            "icon", sa.String(length=16), nullable=False, server_default="✅"
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_routine_steps_routine_id",
        "routine_steps",
        ["routine_id"],
        unique=False,
    )

    op.create_table(
        "routine_progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "routine_id",
            UUID(as_uuid=True),
            sa.ForeignKey("routines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("completion_date", sa.Date(), nullable=False),
        sa.Column(
            "completed_step_ids",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "awarded", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "points_awarded", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "pet_fed", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "routine_id",
            "user_id",
            "completion_date",
            name="uq_routine_progress_day",
        ),
    )
    op.create_index(
        "ix_routine_progress_routine_id",
        "routine_progress",
        ["routine_id"],
        unique=False,
    )
    op.create_index(
        "ix_routine_progress_user_id",
        "routine_progress",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_routine_progress_user_id", table_name="routine_progress"
    )
    op.drop_index(
        "ix_routine_progress_routine_id", table_name="routine_progress"
    )
    op.drop_table("routine_progress")
    op.drop_index(
        "ix_routine_steps_routine_id", table_name="routine_steps"
    )
    op.drop_table("routine_steps")
    op.drop_index("ix_routines_is_active", table_name="routines")
    op.drop_index("ix_routines_assigned_user_id", table_name="routines")
    op.drop_index("ix_routines_family_id", table_name="routines")
    op.drop_table("routines")
