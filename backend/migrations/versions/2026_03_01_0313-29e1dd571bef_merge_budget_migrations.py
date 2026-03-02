"""merge budget migrations

Revision ID: 29e1dd571bef
Revises: family_actual_budget, budget_sync_state
Create Date: 2026-03-01 03:13:59.571292

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '29e1dd571bef'
down_revision = ('family_actual_budget', 'budget_sync_state')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
