"""gig proof image url + max_gigs plan limits

Revision ID: gig_photo_v1
Revises: gigs_v1_approval
Create Date: 2026-05-23

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import json


revision = "gig_photo_v1"
down_revision = "gigs_v1_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_assignments",
        sa.Column("proof_image_url", sa.String(length=512), nullable=True),
    )

    bind = op.get_bind()

    # Backfill plan limits with max_gigs_per_month
    plans = {
        "free": 3,
        "plus": 30,
        "pro": -1,
    }
    for name, limit in plans.items():
        row = bind.execute(
            sa.text("SELECT limits FROM subscription_plans WHERE name = :n"),
            {"n": name},
        ).scalar_one_or_none()
        if row is None:
            continue
        limits = row if isinstance(row, dict) else json.loads(row)
        limits["max_gigs_per_month"] = limit
        bind.execute(
            sa.text("UPDATE subscription_plans SET limits = CAST(:l AS jsonb) WHERE name = :n"),
            {"l": json.dumps(limits), "n": name},
        )


def downgrade() -> None:
    op.drop_column("task_assignments", "proof_image_url")
    bind = op.get_bind()
    for name in ("free", "plus", "pro"):
        row = bind.execute(
            sa.text("SELECT limits FROM subscription_plans WHERE name = :n"),
            {"n": name},
        ).scalar_one_or_none()
        if row is None:
            continue
        limits = row if isinstance(row, dict) else json.loads(row)
        limits.pop("max_gigs_per_month", None)
        bind.execute(
            sa.text("UPDATE subscription_plans SET limits = CAST(:l AS jsonb) WHERE name = :n"),
            {"l": json.dumps(limits), "n": name},
        )
