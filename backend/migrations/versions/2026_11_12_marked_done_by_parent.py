"""task_assignments.marked_done_by_parent

Revision ID: marked_done_by_parent
Revises: chore_rules_v2
Create Date: 2026-11-12

Flags rows a parent completed retroactively (mark_done_for_kid). Existing
rows read false.
"""
import sqlalchemy as sa
from alembic import op

revision = "marked_done_by_parent"
down_revision = "chore_rules_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_assignments",
        sa.Column("marked_done_by_parent", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("task_assignments", "marked_done_by_parent")
