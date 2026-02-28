"""add family actual budget columns

Revision ID: family_actual_budget
Revises: budget_phase1
Create Date: 2026-02-28 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'family_actual_budget'
down_revision: Union[str, None] = 'budget_phase1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing Family columns for Actual Budget integration"""
    
    # Add join_code column (nullable, unique)
    op.add_column('families', sa.Column('join_code', sa.String(length=10), nullable=True))
    op.create_index(op.f('ix_families_join_code'), 'families', ['join_code'], unique=True)
    
    # Add actual_budget_file_id column (nullable)
    op.add_column('families', sa.Column('actual_budget_file_id', sa.String(length=255), nullable=True))
    
    # Add actual_budget_sync_enabled column (NOT NULL with default FALSE)
    op.add_column('families', sa.Column('actual_budget_sync_enabled', sa.Boolean(), nullable=True))
    op.execute("UPDATE families SET actual_budget_sync_enabled = FALSE WHERE actual_budget_sync_enabled IS NULL")
    op.alter_column('families', 'actual_budget_sync_enabled', nullable=False)


def downgrade() -> None:
    """Remove Family columns added for Actual Budget integration"""
    
    op.drop_index(op.f('ix_families_join_code'), table_name='families')
    op.drop_column('families', 'actual_budget_sync_enabled')
    op.drop_column('families', 'actual_budget_file_id')
    op.drop_column('families', 'join_code')
