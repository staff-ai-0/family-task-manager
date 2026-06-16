"""index budget_transactions fk columns

Revision ID: fcb015024c08
Revises: 7a3b284cde5a
Create Date: 2026-06-15 17:14:33.543155

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fcb015024c08'
down_revision = '7a3b284cde5a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FK columns back every activity / category / payee query; without these
    # indexes those are sequential scans (audit M16).
    op.create_index(
        op.f("ix_budget_transactions_account_id"),
        "budget_transactions", ["account_id"],
    )
    op.create_index(
        op.f("ix_budget_transactions_payee_id"),
        "budget_transactions", ["payee_id"],
    )
    op.create_index(
        op.f("ix_budget_transactions_category_id"),
        "budget_transactions", ["category_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_budget_transactions_category_id"), "budget_transactions")
    op.drop_index(op.f("ix_budget_transactions_payee_id"), "budget_transactions")
    op.drop_index(op.f("ix_budget_transactions_account_id"), "budget_transactions")
