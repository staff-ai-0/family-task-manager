"""Add budget management schema (Phase 1)

Revision ID: budget_phase1
Revises: 4f9fe1177e59
Create Date: 2026-02-28 10:00:00.000000

This migration adds the core budget management tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'budget_phase1'
down_revision = '4f9fe1177e59'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create budget_category_groups table
    op.create_table(
        'budget_category_groups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('sort_order', sa.Integer, server_default='0'),
        sa.Column('is_income', sa.Boolean, server_default='false'),
        sa.Column('hidden', sa.Boolean, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_category_groups_family_id', 'budget_category_groups', ['family_id'])

    # Create budget_categories table
    op.create_table(
        'budget_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('group_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_category_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('sort_order', sa.Integer, server_default='0'),
        sa.Column('hidden', sa.Boolean, server_default='false'),
        sa.Column('rollover_enabled', sa.Boolean, server_default='true'),
        sa.Column('goal_amount', sa.Integer, server_default='0', comment='Monthly goal in cents'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_categories_family_id', 'budget_categories', ['family_id'])

    # Create budget_allocations table
    op.create_table(
        'budget_allocations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_categories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('month', sa.Date, nullable=False, comment='First day of the month'),
        sa.Column('budgeted_amount', sa.Integer, nullable=False, server_default='0', comment='Amount in cents'),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.UniqueConstraint('category_id', 'month', name='uq_allocation_category_month'),
    )
    op.create_index('ix_budget_allocations_family_id', 'budget_allocations', ['family_id'])

    # Create budget_accounts table
    op.create_table(
        'budget_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('type', sa.String(50), nullable=False, comment='checking, savings, credit, investment, loan, other'),
        sa.Column('offbudget', sa.Boolean, server_default='false', comment='Tracking account (not part of budget)'),
        sa.Column('closed', sa.Boolean, server_default='false'),
        sa.Column('notes', sa.Text),
        sa.Column('sort_order', sa.Integer, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_accounts_family_id', 'budget_accounts', ['family_id'])

    # Create budget_payees table
    op.create_table(
        'budget_payees',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_payees_family_id', 'budget_payees', ['family_id'])

    # Create budget_transactions table
    op.create_table(
        'budget_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date, nullable=False),
        sa.Column('amount', sa.Integer, nullable=False, comment='Amount in cents (negative=expense, positive=income)'),
        sa.Column('payee_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_payees.id', ondelete='SET NULL'), nullable=True),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_categories.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notes', sa.Text),
        sa.Column('cleared', sa.Boolean, server_default='false'),
        sa.Column('reconciled', sa.Boolean, server_default='false'),
        sa.Column('imported_id', sa.String(255), comment='For deduplication of imported transactions'),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_transactions.id', ondelete='CASCADE'), nullable=True, comment='For split transactions'),
        sa.Column('is_parent', sa.Boolean, server_default='false', comment='Is this a split parent transaction?'),
        sa.Column('transfer_account_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('budget_accounts.id', ondelete='SET NULL'), nullable=True, comment='Target account for transfers'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_budget_transactions_family_id', 'budget_transactions', ['family_id'])
    op.create_index('ix_budget_transactions_date', 'budget_transactions', ['date'])


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_index('ix_budget_transactions_date', 'budget_transactions')
    op.drop_index('ix_budget_transactions_family_id', 'budget_transactions')
    op.drop_table('budget_transactions')

    op.drop_index('ix_budget_payees_family_id', 'budget_payees')
    op.drop_table('budget_payees')

    op.drop_index('ix_budget_accounts_family_id', 'budget_accounts')
    op.drop_table('budget_accounts')

    op.drop_index('ix_budget_allocations_family_id', 'budget_allocations')
    op.drop_table('budget_allocations')

    op.drop_index('ix_budget_categories_family_id', 'budget_categories')
    op.drop_table('budget_categories')

    op.drop_index('ix_budget_category_groups_family_id', 'budget_category_groups')
    op.drop_table('budget_category_groups')
