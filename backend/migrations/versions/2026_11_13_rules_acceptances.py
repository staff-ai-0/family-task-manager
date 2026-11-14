"""rules_acceptances

Revision ID: rules_acceptances
Revises: marked_done_by_parent
Create Date: 2026-11-13

Per-member acceptance of the family's chore rules, one row per rules version.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "rules_acceptances"
down_revision = "marked_done_by_parent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rules_acceptances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "rules_version", name="uq_rules_acceptances_user_version"),
    )
    op.create_index("ix_rules_acceptances_family_id", "rules_acceptances", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_rules_acceptances_family_id", table_name="rules_acceptances")
    op.drop_table("rules_acceptances")
