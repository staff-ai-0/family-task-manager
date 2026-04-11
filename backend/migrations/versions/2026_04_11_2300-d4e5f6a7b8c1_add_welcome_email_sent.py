"""add welcome_email_sent column to users

Revision ID: d4e5f6a7b8c1
Revises: c3d4e5f6a7b9
Create Date: 2026-04-11 23:00:00.000000

Adds a boolean flag tracking whether the welcome onboarding email has
been dispatched for a given user. Used by
EmailService.send_welcome_if_not_sent as an idempotency guard so that
every code path creating a user can fire the welcome without risking
duplicate sends.

Existing rows default to False via the server default, so users who
existed before this migration ran will appear to have never received
the welcome. That's intentional — see the "non-goals" section of
docs/superpowers/specs/2026-04-11-welcome-email-onboarding-design.md
for why backfill was explicitly out of scope.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c1"
down_revision: Union[str, None] = "c3d4e5f6a7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "welcome_email_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "welcome_email_sent")
