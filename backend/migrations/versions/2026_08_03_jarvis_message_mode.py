"""jarvis_messages.mode — copilot vs support thread separation

Support mode (the support-ftm agent, platform agents/catalogue) shares the
jarvis_messages table but must never mix threads, daily caps, or clears with
the copilot: every query site filters on mode. Existing rows are backfilled
to 'copilot' so those filters stay simple (no NULL branch at read time).

Revision ID: jarvis_message_mode
Revises: migrate_referral_bonus_to_grants
Create Date: 2026-08-03
"""
import sqlalchemy as sa
from alembic import op

revision = "jarvis_message_mode"
down_revision = "migrate_referral_bonus_to_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jarvis_messages",
        sa.Column(
            "mode", sa.String(length=16), nullable=True, server_default="copilot"
        ),
    )
    # server_default covers rows created after this migration; existing rows
    # get an explicit backfill so no NULL ever reaches the mode filters.
    op.execute("UPDATE jarvis_messages SET mode = 'copilot' WHERE mode IS NULL")


def downgrade() -> None:
    op.drop_column("jarvis_messages", "mode")
