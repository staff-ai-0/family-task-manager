"""create reward_redemptions table (parent-approval reward queue)

Revision ID: reward_redemptions
Revises: two_currency_economy
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'reward_redemptions'
down_revision = 'two_currency_economy'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'reward_redemptions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('reward_id', UUID(as_uuid=True),
                  sa.ForeignKey('rewards.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reward_title', sa.String(length=200), nullable=False),
        sa.Column('points_cost', sa.Integer(), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family_id', UUID(as_uuid=True),
                  sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('decided_by', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_notes', sa.Text(), nullable=True),
        sa.Column('transaction_id', UUID(as_uuid=True),
                  sa.ForeignKey('point_transactions.id', ondelete='SET NULL'), nullable=True),
    )
    op.create_index('ix_reward_redemptions_user_id', 'reward_redemptions', ['user_id'])
    op.create_index('ix_reward_redemptions_family_id', 'reward_redemptions', ['family_id'])
    op.create_index('ix_reward_redemptions_status', 'reward_redemptions', ['status'])


def downgrade() -> None:
    op.drop_index('ix_reward_redemptions_status', table_name='reward_redemptions')
    op.drop_index('ix_reward_redemptions_family_id', table_name='reward_redemptions')
    op.drop_index('ix_reward_redemptions_user_id', table_name='reward_redemptions')
    op.drop_table('reward_redemptions')
