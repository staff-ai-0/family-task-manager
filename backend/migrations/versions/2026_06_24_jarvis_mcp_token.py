"""create jarvis_mcp_tokens table

Revision ID: jarvis_mcp_token
Revises: jarvis_pending_action
Create Date: 2026-06-24

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'jarvis_mcp_token'
down_revision = 'jarvis_pending_action'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jarvis_mcp_tokens',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'family_id', UUID(as_uuid=True),
            sa.ForeignKey('families.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'created_by', UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('label', sa.String(length=128), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('token_prefix', sa.String(length=8), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_jarvis_mcp_tokens_id', 'jarvis_mcp_tokens', ['id'])
    op.create_index('ix_jarvis_mcp_tokens_family_id', 'jarvis_mcp_tokens', ['family_id'])
    op.create_index('ix_jarvis_mcp_tokens_created_by', 'jarvis_mcp_tokens', ['created_by'])
    op.create_index('ix_jarvis_mcp_tokens_token_hash', 'jarvis_mcp_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_jarvis_mcp_tokens_token_hash', table_name='jarvis_mcp_tokens')
    op.drop_index('ix_jarvis_mcp_tokens_created_by', table_name='jarvis_mcp_tokens')
    op.drop_index('ix_jarvis_mcp_tokens_family_id', table_name='jarvis_mcp_tokens')
    op.drop_index('ix_jarvis_mcp_tokens_id', table_name='jarvis_mcp_tokens')
    op.drop_table('jarvis_mcp_tokens')
