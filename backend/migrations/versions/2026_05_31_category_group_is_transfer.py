"""add is_transfer to budget_category_groups (transfer category bucket)

Revision ID: group_is_transfer
Revises: payee_default_category
Create Date: 2026-05-31

Transfers between accounts (e.g. "Transferencia a BBVA", card payments, ATM
withdrawals) are neither income nor spending. A transfer group flags those so
spending/income reports can exclude them while they stay organized instead of
"Sin categoría".
"""

import sqlalchemy as sa
from alembic import op

revision = "group_is_transfer"
down_revision = "payee_default_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budget_category_groups",
        sa.Column(
            "is_transfer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("budget_category_groups", "is_transfer")
