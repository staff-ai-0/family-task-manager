"""add onboarding columns to families

Revision ID: onboarding_columns
Revises: user_reward_goals
Create Date: 2026-06-10

"""
from alembic import op
import sqlalchemy as sa

revision = 'onboarding_columns'
down_revision = 'user_reward_goals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in [
        'onboarding_child_invited',
        'onboarding_task_created',
        'onboarding_reward_created',
        'onboarding_points_awarded',
        'onboarding_dismissed',
    ]:
        op.add_column(
            'families',
            sa.Column(col, sa.Boolean(), nullable=False, server_default='false'),
        )


def downgrade() -> None:
    for col in [
        'onboarding_dismissed',
        'onboarding_points_awarded',
        'onboarding_reward_created',
        'onboarding_task_created',
        'onboarding_child_invited',
    ]:
        op.drop_column('families', col)
