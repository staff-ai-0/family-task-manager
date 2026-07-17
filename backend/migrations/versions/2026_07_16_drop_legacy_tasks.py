"""Drop the legacy tasks table and its orphan FK columns.

The pre-2026 task system (routes/tasks.py, task_service.py) was deleted in
the 2026-07-16 forensic cleanup — the route was never registered and nothing
writes these rows. Production data was fully reset 2026-06-23, so the table
and both referencing columns are empty everywhere.

Revision ID: drop_legacy_tasks
Revises: gig_claim_comments
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "drop_legacy_tasks"
down_revision = "gig_claim_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dropping the columns drops their FK constraints with them.
    op.drop_column("point_transactions", "task_id")
    op.drop_column("consequences", "triggered_by_task_id")
    op.drop_table("tasks")
    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS taskfrequency")


def downgrade() -> None:
    # NOTE: no explicit Enum.create() here — op.create_table auto-creates the
    # PG types for sa.Enum columns, and doing both raises DuplicateObject
    # (caught by the CI downgrade round-trip on this file's first run).
    taskstatus = sa.Enum("PENDING", "COMPLETED", "OVERDUE", "CANCELLED", name="taskstatus")
    taskfrequency = sa.Enum("DAILY", "WEEKLY", "MONTHLY", "ONE_TIME", name="taskfrequency")

    op.create_table(
        "tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, index=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("points", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("frequency", taskfrequency, nullable=False, server_default="DAILY"),
        sa.Column("status", taskstatus, nullable=False, server_default="PENDING", index=True),
        sa.Column(
            "assigned_to",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "point_transactions",
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "consequences",
        sa.Column(
            "triggered_by_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
