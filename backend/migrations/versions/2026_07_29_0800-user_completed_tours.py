"""add completed_tours to users

The welcome tour is tracked by a single boolean (users.completed_welcome_tour),
which is enough for exactly one tour. The per-module tours (budget, gigs,
chores, rewards) need per-tour state, so this adds a JSONB list of finished
tour ids rather than a boolean column per tour: the set grows with the product,
and a tour is a UX affordance rather than a permission.

Not null with a '[]' server default, so every existing row starts with no tours
completed and sees each module tour once. completed_welcome_tour is left alone —
it predates this and keeps its own endpoint.

Revision ID: user_completed_tours
Revises: point_tx_family_id
Create Date: 2026-07-29 08:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'user_completed_tours'
down_revision = 'point_tx_family_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'completed_tours',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'completed_tours')
