"""acknowledged_gigs_intro flag on users

Revision ID: gigs_intro_ack
Revises: gig_photo_v1
Create Date: 2026-05-24

Adds a one-time-banner ack flag for the mandatory=0 / gigs=points
scope change. Banner shows on first login post-deploy and is dismissed
permanently by hitting POST /api/auth/ack-gigs-intro.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "gigs_intro_ack"
down_revision = "gig_photo_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "acknowledged_gigs_intro",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "acknowledged_gigs_intro")
