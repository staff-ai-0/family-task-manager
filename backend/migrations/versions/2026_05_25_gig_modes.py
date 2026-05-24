"""task_templates.gig_mode (W4.1)

Revision ID: gig_mode_v1
Revises: kiosk_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "gig_mode_v1"
down_revision = "kiosk_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "gig_mode",
            sa.String(length=16),
            nullable=False,
            server_default="claim",
        ),
    )
    op.add_column(
        "task_templates",
        sa.Column(
            "collaboration_min_count",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )
    op.create_check_constraint(
        "chk_gig_mode_valid",
        "task_templates",
        "gig_mode IN ('claim', 'rotation', 'competition', 'collaboration')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_gig_mode_valid", "task_templates", type_="check")
    op.drop_column("task_templates", "collaboration_min_count")
    op.drop_column("task_templates", "gig_mode")
