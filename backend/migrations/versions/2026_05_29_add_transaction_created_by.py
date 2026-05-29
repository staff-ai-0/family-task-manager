"""add created_by_id to budget_transactions

Revision ID: txn_created_by
Revises: wave4_scanner_v2
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "txn_created_by"
down_revision = "wave4_scanner_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_transactions",
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # created_at DESC matches the AccountMatchingService Strategy 3a query
    # (ORDER BY created_at DESC LIMIT 1) so the planner can read the index
    # in physical order without an extra sort step.
    op.create_index(
        "ix_budget_transactions_created_by",
        "budget_transactions",
        ["family_id", "created_by_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_transactions_created_by", table_name="budget_transactions")
    op.drop_column("budget_transactions", "created_by_id")
