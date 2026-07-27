"""Add users.is_superadmin — the platform-operator flag.

Half of the super-admin gate: a user is an operator only when this column is
true AND their email appears in the SUPERADMIN_EMAILS env allowlist. Split
deliberately so neither a stolen database dump nor an env edit alone is
sufficient to mint an operator.

Revision ID: superadmin_flag
Revises: drop_budget_sync_state
"""
import sqlalchemy as sa
from alembic import op

revision = "superadmin_flag"
down_revision = "drop_budget_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_superadmin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_superadmin")
