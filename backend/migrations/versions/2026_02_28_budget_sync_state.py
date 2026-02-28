"""Add budget sync state table

Revision ID: budget_sync_state
Revises: budget_phase1
Create Date: 2026-02-28 14:00:00.000000

This migration adds the budget_sync_state table for tracking point-to-budget synchronization.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'budget_sync_state'
down_revision = 'budget_phase1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create budget_sync_state table
    op.create_table(
        'budget_sync_state',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('last_sync_to_budget', sa.DateTime(timezone=True), nullable=True, comment='Last time points were synced to budget'),
        sa.Column('last_sync_from_budget', sa.DateTime(timezone=True), nullable=True, comment='Last time budget transactions were synced'),
        sa.Column('synced_point_transactions', postgresql.JSONB, nullable=False, server_default='{}', comment='Map of FTM transaction ID -> budget transaction ID'),
        sa.Column('synced_budget_transactions', postgresql.JSONB, nullable=False, server_default='{}', comment='Map of budget transaction ID -> FTM transaction ID'),
        sa.Column('sync_errors', postgresql.JSONB, nullable=False, server_default='[]', comment='Recent sync errors'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_sync_state_family_id', 'budget_sync_state', ['family_id'])


def downgrade() -> None:
    op.drop_index('ix_budget_sync_state_family_id', 'budget_sync_state')
    op.drop_table('budget_sync_state')
