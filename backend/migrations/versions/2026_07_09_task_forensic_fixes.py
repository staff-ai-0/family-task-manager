"""Task workflow forensic fixes.

- Repoint the assignments hot-path index: the composite (family_id, due_date)
  sat on a column no query ever filtered (due_date was never even written
  before this change). The sweeps and kid due-today lists actually filter
  (family_id, assigned_date) — index that instead.
- task_templates.days_of_week (JSONB, nullable): optional explicit weekdays
  (Mon=0..Sun=6) refining the weekly expansion.

Revision ID: task_forensic_fixes
Revises: routines_library
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "task_forensic_fixes"
down_revision = "routines_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_task_assignments_family_assigned",
        "task_assignments",
        ["family_id", "assigned_date"],
        if_not_exists=True,
    )
    op.drop_index(
        "ix_task_assignments_family_due",
        table_name="task_assignments",
        if_exists=True,
    )
    op.add_column(
        "task_templates",
        sa.Column("days_of_week", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_templates", "days_of_week")
    op.create_index(
        "ix_task_assignments_family_due",
        "task_assignments",
        ["family_id", "due_date"],
        if_not_exists=True,
    )
    op.drop_index(
        "ix_task_assignments_family_assigned",
        table_name="task_assignments",
        if_exists=True,
    )
