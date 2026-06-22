"""add completed_welcome_tour flag to users

Revision ID: welcome_tour_flag
Revises: eccb2d1e53e2
Create Date: 2026-06-22

"""
from alembic import op
import sqlalchemy as sa

revision = 'welcome_tour_flag'
down_revision = 'eccb2d1e53e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'completed_welcome_tour',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
    # Existing accounts are already onboarded — mark them done so the welcome
    # tour only auto-starts for NEW users created after this migration (whose
    # rows default to false). Without this, every current family would be shown
    # the tour once on their next visit after deploy.
    op.execute("UPDATE users SET completed_welcome_tour = true")


def downgrade() -> None:
    op.drop_column('users', 'completed_welcome_tour')
