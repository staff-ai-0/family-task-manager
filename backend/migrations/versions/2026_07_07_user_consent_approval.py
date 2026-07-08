"""user consent capture + join-code parental approval + birthdate

Adds to users:
- consented_at / consent_policy_version: terms + privacy-notice acceptance
  recorded at registration (family founders must accept; version tag
  '2026-07-07-v1' — bump on material changes to /terminos or /privacidad).
- approval_status ('approved' | 'pending') + approved_at: join-by-family-code
  self-signups start 'pending' and cannot log in until a parent approves
  (POST /api/users/{id}/approve). All pre-existing rows and trusted creation
  paths default to 'approved'.
- birthdate: optional DOB for child/teen members (future age gating; no hard
  logic yet).

Revision ID: user_consent_approval
Revises: billing_robustness
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = 'user_consent_approval'
down_revision = 'billing_robustness'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('consented_at', sa.DateTime(), nullable=True))
    op.add_column(
        'users',
        sa.Column('consent_policy_version', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'approval_status',
            sa.String(length=16),
            nullable=False,
            server_default='approved',
        ),
    )
    op.create_index(
        'ix_users_approval_status', 'users', ['approval_status']
    )
    op.add_column('users', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('birthdate', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'birthdate')
    op.drop_column('users', 'approved_at')
    op.drop_index('ix_users_approval_status', table_name='users')
    op.drop_column('users', 'approval_status')
    op.drop_column('users', 'consent_policy_version')
    op.drop_column('users', 'consented_at')
