"""gig claim state + claimed_at column

Revision ID: gig_claim_v1
Revises: gigs_intro_ack
Create Date: 2026-05-24

Adds CLAIMED to the assignment status enum and a claimed_at timestamp.
Lets children reserve a gig before doing it. Per-user assignments
already exist, so claim is a workflow gate rather than collision
avoidance — once claimed the row is committed to delivering proof.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "gig_claim_v1"
down_revision = "gigs_intro_ack"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres-side: add the enum value.
    op.execute("ALTER TYPE assignmentstatus ADD VALUE IF NOT EXISTS 'claimed'")
    op.add_column(
        "task_assignments",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_assignments", "claimed_at")
    # NOTE: Postgres has no DROP VALUE for enums. Downgrade leaves the
    # 'claimed' value in place; it becomes orphan but harmless. A full
    # downgrade would require recreating the enum type.
