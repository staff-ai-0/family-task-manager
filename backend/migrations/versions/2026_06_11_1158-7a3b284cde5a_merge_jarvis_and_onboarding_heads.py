"""merge_jarvis_and_onboarding_heads

Revision ID: 7a3b284cde5a
Revises: jarvis_rename_v1, onboarding_columns
Create Date: 2026-06-11 11:58:33.772714

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a3b284cde5a'
down_revision = ('jarvis_rename_v1', 'onboarding_columns')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
