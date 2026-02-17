"""add_is_default_to_rewards

Revision ID: 0bf3ae3793da
Revises: 8d23a3796561
Create Date: 2026-01-26 02:18:49.496615

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0bf3ae3793da'
down_revision = '8d23a3796561'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_default column to rewards table with server_default for existing rows
    op.add_column('rewards', sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('rewards', 'is_default')
