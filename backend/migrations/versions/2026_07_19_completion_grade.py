"""Graded task review: completion_grade + partial_credit_pct.

Revision ID: completion_grade
Revises: family_gig_term
"""
import sqlalchemy as sa
from alembic import op

revision = "completion_grade"
down_revision = "family_gig_term"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_assignments",
        sa.Column("completion_grade", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "task_assignments",
        sa.Column("partial_credit_pct", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_task_assignments_completion_grade",
        "task_assignments",
        "completion_grade IN ('full','partial','missed')",
    )
    op.create_check_constraint(
        "ck_task_assignments_partial_credit_pct",
        "task_assignments",
        "partial_credit_pct >= 0 AND partial_credit_pct <= 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_task_assignments_partial_credit_pct", "task_assignments", type_="check"
    )
    op.drop_constraint(
        "ck_task_assignments_completion_grade", "task_assignments", type_="check"
    )
    op.drop_column("task_assignments", "partial_credit_pct")
    op.drop_column("task_assignments", "completion_grade")
