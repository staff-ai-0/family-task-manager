"""Single-slot gigs: gig_offerings.allow_multiple (default false).

By default the first approved claim now closes the offering and releases the
other active claims — a family should never pay twice for the same job unless
the gig is explicitly marked multi-kid.

Revision ID: gig_allow_multiple
Revises: paycheck_reminder_week
"""
import sqlalchemy as sa
from alembic import op

revision = "gig_allow_multiple"
down_revision = "paycheck_reminder_week"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gig_offerings",
        sa.Column(
            "allow_multiple",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("gig_offerings", "allow_multiple")
