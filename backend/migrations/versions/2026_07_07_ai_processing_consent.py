"""parental opt-in for AI processing of kid-generated content

Adds to families:
- ai_processing_consent (bool, NOT NULL, default false): when false, AI paths
  that process KID-generated content are skipped — gig proof photos fall back
  to manual parent approval and Jarvis/MCP chat-reading tools are disabled.
  Parent-initiated AI flows on parent content (receipt scan, calendar scan,
  recipe import, Jarvis general chat) are NOT gated — they are disclosed in
  /privacidad and are the parent's own action.
- ai_processing_consent_at (nullable datetime): stamped whenever a parent
  decides (either way). NULL means "never asked/decided" so the dashboard can
  show a one-time prompt banner.

Default is false for ALL rows (including pre-existing families): the honest
approach — the consent UI prompts the parent once instead of assuming consent.

Revision ID: ai_processing_consent
Revises: user_consent_approval
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = 'ai_processing_consent'
down_revision = 'user_consent_approval'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'families',
        sa.Column(
            'ai_processing_consent',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
    op.add_column(
        'families',
        sa.Column('ai_processing_consent_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('families', 'ai_processing_consent_at')
    op.drop_column('families', 'ai_processing_consent')
