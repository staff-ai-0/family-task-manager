"""Add users.last_seen_at — throttled activity stamp.

The single prerequisite for DAU/WAU, retention, dormant-tenant detection and
every "is this family alive?" answer in the support console. Recorded now
because activity history that is not captured cannot be reconstructed later.

Revision ID: user_last_seen_at
Revises: operator_audit_log
"""
import sqlalchemy as sa
from alembic import op

revision = "user_last_seen_at"
down_revision = "operator_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_seen_at")
