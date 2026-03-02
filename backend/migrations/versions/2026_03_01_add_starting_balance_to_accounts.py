"""add_starting_balance_to_budget_accounts

Revision ID: add_starting_balance_v1
Revises: a6d655cbc18c
Create Date: 2026-03-01 12:00:00.000000

Adds starting_balance column to budget_accounts table.
This enables correct envelope budgeting: the starting balance
represents the account balance at the time of account creation,
stored as a synthetic starting-balance transaction in budget_transactions.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_starting_balance_v1'
down_revision = 'a6d655cbc18c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add starting_balance column to budget_accounts
    # This stores the initial balance in cents at account creation time
    op.add_column(
        'budget_accounts',
        sa.Column(
            'starting_balance',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Initial account balance in cents at creation time'
        )
    )


def downgrade() -> None:
    op.drop_column('budget_accounts', 'starting_balance')
