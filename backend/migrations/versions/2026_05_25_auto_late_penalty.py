"""task_templates auto late penalty fields

Revision ID: late_pen_v1
Revises: tmpl_effort_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "late_pen_v1"
down_revision = "tmpl_effort_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "auto_late_penalty",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "task_templates",
        sa.Column("late_restriction_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "task_templates",
        sa.Column("late_severity", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "task_templates",
        sa.Column(
            "late_duration_days",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "chk_late_duration_positive",
        "task_templates",
        "late_duration_days >= 1 AND late_duration_days <= 30",
    )


def downgrade() -> None:
    op.drop_constraint(
        "chk_late_duration_positive", "task_templates", type_="check"
    )
    op.drop_column("task_templates", "late_duration_days")
    op.drop_column("task_templates", "late_severity")
    op.drop_column("task_templates", "late_restriction_type")
    op.drop_column("task_templates", "auto_late_penalty")
