"""merge token_version and fk_indexes heads

Revision ID: eccb2d1e53e2
Revises: 02b4ae6958cc, fcb015024c08
Create Date: 2026-06-16 01:51:27.732322

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eccb2d1e53e2'
down_revision = ('02b4ae6958cc', 'fcb015024c08')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
