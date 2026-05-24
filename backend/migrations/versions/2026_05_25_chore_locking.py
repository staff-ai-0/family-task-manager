"""task_templates.blocks_rewards — chore locking

Revision ID: chore_lock_v1
Revises: late_pen_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "chore_lock_v1"
down_revision = "late_pen_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "blocks_rewards",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("task_templates", "blocks_rewards")
