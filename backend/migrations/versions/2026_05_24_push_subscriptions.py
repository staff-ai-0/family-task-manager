"""push_subscriptions table for Web Push (VAPID)

Revision ID: push_subs_v1
Revises: gig_trust_v1
Create Date: 2026-05-24

Stores PushSubscription rows produced by the browser's PushManager so
the backend can fan out gig-pending notifications to a parent's devices.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "push_subs_v1"
down_revision = "gig_trust_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("endpoint", sa.String(length=2048), nullable=False),
        sa.Column("p256dh", sa.String(length=255), nullable=False),
        sa.Column("auth", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_unique_constraint(
        "uq_push_subscriptions_user_endpoint",
        "push_subscriptions",
        ["user_id", "endpoint"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_push_subscriptions_user_endpoint",
        "push_subscriptions",
        type_="unique",
    )
    op.drop_table("push_subscriptions")
