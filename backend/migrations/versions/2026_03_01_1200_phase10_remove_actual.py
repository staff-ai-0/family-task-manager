"""Phase 10: Remove Actual Budget integration columns

Revision ID: phase10_remove_actual
Revises: 29e1dd571bef
Create Date: 2026-03-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'phase10_remove_actual'
down_revision = '29e1dd571bef'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove Actual Budget integration columns from families table."""
    # Drop actual_budget_sync_enabled column
    op.drop_column('families', 'actual_budget_sync_enabled')
    
    # Drop actual_budget_file_id column
    op.drop_column('families', 'actual_budget_file_id')


def downgrade() -> None:
    """Re-add Actual Budget integration columns (for rollback)."""
    # Add back actual_budget_file_id column
    op.add_column(
        'families',
        sa.Column(
            'actual_budget_file_id',
            sa.String(255),
            nullable=True,
            comment='Actual Budget file ID for this family'
        )
    )
    
    # Add back actual_budget_sync_enabled column
    op.add_column(
        'families',
        sa.Column(
            'actual_budget_sync_enabled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Enable sync with Actual Budget'
        )
    )
