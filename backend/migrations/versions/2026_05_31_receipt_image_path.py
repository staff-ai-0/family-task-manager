"""receipt_image_path on budget_transactions

Revision ID: receipt_image_path
Revises: txn_created_by
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa


revision = "receipt_image_path"
down_revision = "txn_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_transactions",
        sa.Column("receipt_image_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("budget_transactions", "receipt_image_path")
