"""user_reward_goals table

Revision ID: user_reward_goals
Revises: gig_tables
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'user_reward_goals'
down_revision = 'gig_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_reward_goals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('reward_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('rewards.id', ondelete='CASCADE'), nullable=False),
        sa.Column('set_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('achieved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('nudge_sent_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_user_reward_goals_user_id', 'user_reward_goals', ['user_id'])
    op.create_index('ix_user_reward_goals_family_id', 'user_reward_goals', ['family_id'])
    # One active goal per user, enforced at DB level
    op.execute(
        "CREATE UNIQUE INDEX ix_user_reward_goals_user_active "
        "ON user_reward_goals (user_id) WHERE achieved_at IS NULL"
    )


def downgrade() -> None:
    op.drop_table('user_reward_goals')
