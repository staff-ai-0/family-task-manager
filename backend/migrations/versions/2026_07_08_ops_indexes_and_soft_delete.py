"""Ops: hot-path composite indexes + Family/User soft-delete

Two independent ops/data-safety improvements in ONE revision:

  1. COMPOSITE INDEXES on the three heaviest family-scoped read paths. Every
     list query already filters family_id and then orders/filters by a time
     column; the single-column indexes force a filter-then-sort. These composite
     btrees let Postgres satisfy filter + order in one index scan:
       - budget_transactions  (family_id, date DESC)   — transaction list
       - family_chat_messages (family_id, created_at)   — chat thread paging
       - task_assignments     (family_id, due_date)     — due/overdue sweeps
     Mirrored in the models' __table_args__ so they stay declared.

  2. SOFT-DELETE for families + users. Self-serve family deletion now stamps
     families.deleted_at (+ every member's users.deleted_at) instead of an
     immediate hard cascade. Auth treats a soft-deleted user/family as gone
     (401). A daily purge sweep hard-deletes families past the grace window
     (FamilyDeletionService.PURGE_RETENTION_DAYS). families.deleted_at is
     indexed so the sweep's `WHERE deleted_at < cutoff` is cheap.

Both columns are nullable with no default — instant on PG15, no backfill.
Downgrade drops the indexes + columns.

Revision ID: ops_indexes_soft_delete
Revises: savings_goal_star_mode
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "ops_indexes_soft_delete"
down_revision = "savings_goal_star_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Composite hot-path indexes.
    op.create_index(
        "ix_budget_transactions_family_date",
        "budget_transactions",
        ["family_id", sa.text("date DESC")],
        unique=False,
    )
    op.create_index(
        "ix_family_chat_messages_family_created",
        "family_chat_messages",
        ["family_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_assignments_family_due",
        "task_assignments",
        ["family_id", "due_date"],
        unique=False,
    )

    # 2. Soft-delete tombstones.
    op.add_column(
        "families",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexed on families only — the purge sweep scans families by deleted_at;
    # users are reached via the family cascade, not scanned directly.
    op.create_index(
        "ix_families_deleted_at", "families", ["deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_families_deleted_at", table_name="families")
    op.drop_column("users", "deleted_at")
    op.drop_column("families", "deleted_at")

    op.drop_index(
        "ix_task_assignments_family_due", table_name="task_assignments"
    )
    op.drop_index(
        "ix_family_chat_messages_family_created",
        table_name="family_chat_messages",
    )
    op.drop_index(
        "ix_budget_transactions_family_date", table_name="budget_transactions"
    )
