"""task_templates.effort_level

Revision ID: tmpl_effort_v1
Revises: push_subs_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "tmpl_effort_v1"
down_revision = "push_subs_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "effort_level",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_check_constraint(
        "chk_effort_level_range",
        "task_templates",
        "effort_level BETWEEN 1 AND 3",
    )


def downgrade() -> None:
    op.drop_constraint("chk_effort_level_range", "task_templates", type_="check")
    op.drop_column("task_templates", "effort_level")
