"""teen_checkins + families.teen_checkin_enabled (Jarvis teen check-in)

Revision ID: teen_checkins
Revises: family_smart_reminders
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "teen_checkins"
down_revision = "family_smart_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No default: NULL = undecided. Check-ins store a minor's answers for the
    # product team, so every family — existing and new — must say yes first.
    op.add_column("families", sa.Column("teen_checkin_enabled", sa.Boolean(), nullable=True))
    # When a parent last answered — the record of the consent itself.
    op.add_column("families", sa.Column("teen_checkin_decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "teen_checkins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(16), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("days_late", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "user_id", "assignment_id", name="uq_teen_checkins_family_user_assignment"),
        sa.CheckConstraint("trigger IN ('late','sent_back')", name="ck_teen_checkins_trigger"),
        sa.CheckConstraint("outcome IN ('answered','dismissed')", name="ck_teen_checkins_outcome"),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN "
            "('too_hard','not_clear','no_time','not_fair','forgot','app_problem','other')",
            name="ck_teen_checkins_reason",
        ),
        sa.CheckConstraint("(outcome = 'answered') = (reason IS NOT NULL)", name="ck_teen_checkins_reason_iff_answered"),
        sa.CheckConstraint("note IS NULL OR reason IN ('app_problem','other')", name="ck_teen_checkins_note_reason"),
        sa.CheckConstraint("note IS NULL OR char_length(note) <= 200", name="ck_teen_checkins_note_len"),
        sa.CheckConstraint("days_late >= 0", name="ck_teen_checkins_days_late"),
    )
    op.create_index("ix_teen_checkins_family_id", "teen_checkins", ["family_id"])
    op.create_index("ix_teen_checkins_user_id", "teen_checkins", ["user_id"])
    op.create_index("ix_teen_checkins_created_at", "teen_checkins", ["created_at"])
    # Deleting a chore sets assignment_id NULL here: without an index that is a table scan.
    op.create_index("ix_teen_checkins_assignment_id", "teen_checkins", ["assignment_id"])


def downgrade() -> None:
    op.drop_index("ix_teen_checkins_assignment_id", table_name="teen_checkins")
    op.drop_index("ix_teen_checkins_created_at", table_name="teen_checkins")
    op.drop_index("ix_teen_checkins_user_id", table_name="teen_checkins")
    op.drop_index("ix_teen_checkins_family_id", table_name="teen_checkins")
    op.drop_table("teen_checkins")
    op.drop_column("families", "teen_checkin_decided_at")
    op.drop_column("families", "teen_checkin_enabled")
