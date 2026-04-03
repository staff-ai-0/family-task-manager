"""wave2: saved filters, tags, rule actions

Revision ID: a1b2c3d4e5f7
Revises: 586649b5ef22
Create Date: 2026-04-02 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f7'
down_revision = '586649b5ef22'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Feature 4: Saved Transaction Filters ---
    op.create_table(
        'budget_saved_filters',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('family_id', UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('conditions', JSONB, nullable=False),
        sa.Column('conditions_op', sa.String(10), nullable=False, server_default='and'),
        sa.Column('created_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Feature 5: Advanced Rule Actions ---
    op.add_column(
        'budget_categorization_rules',
        sa.Column('actions', JSONB, nullable=True, comment='Multi-field actions: [{field, operation, value}, ...]'),
    )

    # --- Feature 6: Tags ---
    op.create_table(
        'budget_tags',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('family_id', UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('family_id', 'name', name='uq_tag_family_name'),
    )

    op.create_table(
        'budget_transaction_tags',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('transaction_id', UUID(as_uuid=True), sa.ForeignKey('budget_transactions.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('tag_id', UUID(as_uuid=True), sa.ForeignKey('budget_tags.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.UniqueConstraint('transaction_id', 'tag_id', name='uq_transaction_tag'),
    )


def downgrade() -> None:
    op.drop_table('budget_transaction_tags')
    op.drop_table('budget_tags')
    op.drop_column('budget_categorization_rules', 'actions')
    op.drop_table('budget_saved_filters')
