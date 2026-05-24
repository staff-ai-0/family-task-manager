"""task_assignments AI validation columns (W3.1)

Revision ID: ai_val_v1
Revises: cal_evt_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "ai_val_v1"
down_revision = "cal_evt_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_assignments",
        sa.Column("ai_validation_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "task_assignments",
        sa.Column("ai_validation_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_assignments", "ai_validation_notes")
    op.drop_column("task_assignments", "ai_validation_score")
