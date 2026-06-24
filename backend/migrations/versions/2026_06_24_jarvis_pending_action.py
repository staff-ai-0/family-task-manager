"""create jarvis_pending_actions table

Revision ID: jarvis_pending_action
Revises: onboarding_events
Create Date: 2026-06-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'jarvis_pending_action'
down_revision = 'onboarding_events'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jarvis_pending_actions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'family_id', UUID(as_uuid=True),
            sa.ForeignKey('families.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'user_id', UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'message_id', UUID(as_uuid=True),
            sa.ForeignKey('jarvis_messages.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('tool_name', sa.String(length=128), nullable=False),
        sa.Column('params', JSONB(), nullable=False, server_default='{}'),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name='chk_jarvis_pending_action_status',
        ),
    )
    op.create_index('ix_jarvis_pending_actions_family_id', 'jarvis_pending_actions', ['family_id'])
    op.create_index('ix_jarvis_pending_actions_user_id', 'jarvis_pending_actions', ['user_id'])
    op.create_index('ix_jarvis_pending_actions_id', 'jarvis_pending_actions', ['id'])


def downgrade() -> None:
    op.drop_index('ix_jarvis_pending_actions_id', table_name='jarvis_pending_actions')
    op.drop_index('ix_jarvis_pending_actions_user_id', table_name='jarvis_pending_actions')
    op.drop_index('ix_jarvis_pending_actions_family_id', table_name='jarvis_pending_actions')
    op.drop_table('jarvis_pending_actions')
