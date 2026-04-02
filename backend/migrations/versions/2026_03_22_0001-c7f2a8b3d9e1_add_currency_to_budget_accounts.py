"""Add currency field to budget_accounts

Revision ID: c7f2a8b3d9e1
Revises: 71e36cd7ea5a
Create Date: 2026-03-22 00:01:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7f2a8b3d9e1'
down_revision = '71e36cd7ea5a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'budget_accounts',
        sa.Column(
            'currency',
            sa.String(3),
            nullable=False,
            server_default='MXN',
            comment='ISO 4217 currency code (e.g. MXN, USD, EUR)',
        ),
    )


def downgrade() -> None:
    op.drop_column('budget_accounts', 'currency')
