"""user gig_trust_streak counter for auto-approval

Revision ID: gig_trust_v1
Revises: gig_claim_v1
Create Date: 2026-05-24

Adds an integer counter tracking consecutive approved gigs per user.
Once the counter hits the configured threshold (GIG_AUTO_APPROVE_STREAK,
default 3), subsequent gigs auto-approve on completion. A parent
rejection resets the counter to zero.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "gig_trust_v1"
down_revision = "gig_claim_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "gig_trust_streak",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "gig_trust_streak")
