"""Actual-Budget-parity fixes.

- budget_receipt_drafts.account_id → nullable: a family with zero accounts
  can still scan; the reviewer picks an account at approval time.

Revision ID: budget_parity
Revises: budget_catalog_dedupe
"""
from alembic import op

revision = "budget_parity"
down_revision = "budget_catalog_dedupe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "budget_receipt_drafts", "account_id",
        existing_type=None, nullable=True,
    )


def downgrade() -> None:
    # Backfill any NULLs before re-tightening would be required; drafts are
    # transient review rows, so deleting account-less ones is acceptable.
    op.execute(
        "DELETE FROM budget_receipt_drafts WHERE account_id IS NULL"
    )
    op.alter_column(
        "budget_receipt_drafts", "account_id",
        existing_type=None, nullable=False,
    )
