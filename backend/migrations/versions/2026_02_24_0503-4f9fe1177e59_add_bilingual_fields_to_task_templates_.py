"""add bilingual fields to task_templates and preferred_lang to users

Revision ID: 4f9fe1177e59
Revises: a1b2c3d4e5f6
Create Date: 2026-02-24 05:03:43.487588

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4f9fe1177e59'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add bilingual fields to task_templates
    op.add_column('task_templates', sa.Column('title_es', sa.String(length=200), nullable=True))
    op.add_column('task_templates', sa.Column('description_es', sa.Text(), nullable=True))

    # Add preferred language to users (defaults to 'en')
    op.add_column('users', sa.Column('preferred_lang', sa.String(length=5), server_default='en', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'preferred_lang')
    op.drop_column('task_templates', 'description_es')
    op.drop_column('task_templates', 'title_es')
