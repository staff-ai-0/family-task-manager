"""create onboarding_events table

Revision ID: onboarding_events
Revises: welcome_tour_flag
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'onboarding_events'
down_revision = 'welcome_tour_flag'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'onboarding_events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family_id', UUID(as_uuid=True),
                  sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(length=40), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_onboarding_events_user_id', 'onboarding_events', ['user_id'])
    op.create_index('ix_onboarding_events_family_id', 'onboarding_events', ['family_id'])


def downgrade() -> None:
    op.drop_index('ix_onboarding_events_family_id', table_name='onboarding_events')
    op.drop_index('ix_onboarding_events_user_id', table_name='onboarding_events')
    op.drop_table('onboarding_events')
