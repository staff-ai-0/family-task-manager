"""add default_category_id to budget_payees (payee category learning)

Revision ID: payee_default_category
Revises: receipt_image_path
Create Date: 2026-05-31

Mirrors Actual Budget's payee default-category: once a payee is associated
with a category, future transactions for that payee inherit it automatically.
"""

import sqlalchemy as sa
from alembic import op

revision = "payee_default_category"
down_revision = "receipt_image_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_payees",
        sa.Column("default_category_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_budget_payees_default_category",
        "budget_payees",
        "budget_categories",
        ["default_category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_budget_payees_default_category", "budget_payees", type_="foreignkey"
    )
    op.drop_column("budget_payees", "default_category_id")
