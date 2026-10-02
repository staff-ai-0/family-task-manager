"""families.smart_reminders_enabled for UX-D4a

Revision ID: family_smart_reminders
Revises: weekly_quests
Create Date: 2026-10-01
"""
import sqlalchemy as sa
from alembic import op

revision = "family_smart_reminders"
down_revision = "weekly_quests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # On for every family, existing ones included: the reminders have no
    # effect on the family economy and only reach devices that allowed push.
    op.add_column(
        "families",
        sa.Column("smart_reminders_enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("families", "smart_reminders_enabled")
