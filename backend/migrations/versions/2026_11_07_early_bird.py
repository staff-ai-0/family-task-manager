"""early_bird — 11:00 chore deadline settings, take-over columns, streak ledger

Revision ID: early_bird
Revises: payout_receipts
Create Date: 2026-11-07

Adds:
  * families.early_bird_* settings (feature OFF by default)
  * task_templates.early_bird_exempt
  * task_assignments.taken_by / taken_at / taken_from_id / early_bonus_points
  * early_bird_weeks (one settled row per teen per week)
  * assignmentstatus value 'taken' (VALUE-valued enum, lowercase)
  * cashtransactiontype value 'BONUS' (UPPERCASE member NAME: the ORM enum has
    no values_callable, see the family_bank migration)

Downgrade: Postgres cannot drop an enum value, so the type is recreated; rows
using the new values are first mapped to 'cancelled' / 'ADJUSTMENT'.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "early_bird"
down_revision = "payout_receipts"
branch_labels = None
depends_on = None

ASSIGNMENT_VALUES = ("pending", "claimed", "completed", "overdue", "cancelled")
CASH_VALUES = (
    "GIG_EARNED", "PAYOUT", "ADJUSTMENT",
    "ALLOWANCE", "INTEREST", "MATCH", "JAR_TRANSFER",
)


def _recreate_enum(type_name: str, table: str, column: str, values: tuple) -> None:
    labels = ", ".join(f"'{v}'" for v in values)
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_old")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({labels})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name} "
        f"USING {column}::text::{type_name}"
    )
    op.execute(f"DROP TYPE {type_name}_old")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'taken'")
        op.execute("ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS 'BONUS'")

    op.add_column("families", sa.Column("early_bird_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("families", sa.Column("early_bird_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("families", sa.Column("early_bird_deadline", sa.Time(), nullable=False, server_default="11:00"))
    op.add_column("families", sa.Column("early_bird_days", postgresql.JSONB(), nullable=True))
    op.add_column("families", sa.Column("early_bird_bonus_pct", sa.Integer(), nullable=False, server_default="20"))
    op.add_column("families", sa.Column("early_bird_week_pct", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("families", sa.Column("early_bird_streak_cents", sa.Integer(), nullable=False, server_default="50000"))

    op.add_column("task_templates", sa.Column("early_bird_exempt", sa.Boolean(), nullable=False, server_default="false"))

    op.add_column("task_assignments", sa.Column("taken_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("task_assignments", sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("task_assignments", sa.Column("taken_from_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True))
    op.add_column("task_assignments", sa.Column("early_bonus_points", sa.Integer(), nullable=True))
    op.create_index("ix_task_assignments_taken_from_id", "task_assignments", ["taken_from_id"])

    op.create_table(
        "early_bird_weeks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_of", sa.Date(), nullable=False),
        sa.Column("result", sa.String(10), nullable=False),
        sa.Column("run_weeks", sa.Integer(), nullable=False),
        sa.Column("bonus_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "week_of", name="uq_early_bird_weeks_user_week"),
        sa.CheckConstraint("result IN ('early','missed','neutral')", name="ck_early_bird_weeks_result"),
    )
    op.create_index("ix_early_bird_weeks_family_id", "early_bird_weeks", ["family_id"])
    op.create_index("ix_early_bird_weeks_user_id", "early_bird_weeks", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_early_bird_weeks_user_id", table_name="early_bird_weeks")
    op.drop_index("ix_early_bird_weeks_family_id", table_name="early_bird_weeks")
    op.drop_table("early_bird_weeks")

    op.drop_index("ix_task_assignments_taken_from_id", table_name="task_assignments")
    for col in ("early_bonus_points", "taken_from_id", "taken_at", "taken_by"):
        op.drop_column("task_assignments", col)
    op.drop_column("task_templates", "early_bird_exempt")
    for col in (
        "early_bird_streak_cents", "early_bird_week_pct", "early_bird_bonus_pct",
        "early_bird_days", "early_bird_deadline", "early_bird_enabled_at", "early_bird_enabled",
    ):
        op.drop_column("families", col)

    op.execute("UPDATE task_assignments SET status = 'cancelled' WHERE status = 'taken'")
    op.execute("UPDATE cash_transactions SET type = 'ADJUSTMENT' WHERE type = 'BONUS'")
    _recreate_enum("assignmentstatus", "task_assignments", "status", ASSIGNMENT_VALUES)
    _recreate_enum("cashtransactiontype", "cash_transactions", "type", CASH_VALUES)
