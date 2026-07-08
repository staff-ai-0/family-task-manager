"""P1-W4 task mechanics upgrades

task_templates:
- requires_proof (bool, NOT NULL, default false): kid must attach a photo on
  completion; the completion enters the parent approval queue (points credit
  on approval) instead of completing silently.
- rotation_cursor (int, NOT NULL, default 0) + rotation_week_of (date, NULL):
  persisted round-robin state for assignment_type='rotate'. The cursor is the
  starting index into assigned_user_ids for the week stored in
  rotation_week_of, making the weekly shuffle deterministic AND continuous
  across weeks (re-shuffling the same week reuses the same start; shuffling
  the next week continues where the previous week ended).
- recurrence_mode (varchar(16), NOT NULL, default 'weekly'): 'weekly' keeps
  the existing weekday expansion; 'since_completion' switches the template to
  interval recurrence — a new assignment spawns N days after the last
  completion (see recur_every_n_days), driven by the hourly sweep.
- recur_every_n_days (int, NULL): the N for 'since_completion' mode.

gig_offerings (kid-proposed gigs):
- status (varchar(16), NOT NULL, default 'approved'): 'approved' (on the
  board), 'pending' (kid proposal awaiting parent review, is_active=false),
  'rejected'.
- review_notes (text, NULL): parent's note on approve/reject.
- reviewed_by (uuid FK users, NULL) + reviewed_at (timestamptz, NULL).

Revision ID: task_mechanics_w4
Revises: ai_processing_consent
Create Date: 2026-07-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'task_mechanics_w4'
down_revision = 'ai_processing_consent'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── task_templates ────────────────────────────────────────────────
    op.add_column(
        'task_templates',
        sa.Column('requires_proof', sa.Boolean(), nullable=False,
                  server_default='false'),
    )
    op.add_column(
        'task_templates',
        sa.Column('rotation_cursor', sa.Integer(), nullable=False,
                  server_default='0'),
    )
    op.add_column(
        'task_templates',
        sa.Column('rotation_week_of', sa.Date(), nullable=True),
    )
    op.add_column(
        'task_templates',
        sa.Column('recurrence_mode', sa.String(length=16), nullable=False,
                  server_default='weekly'),
    )
    op.add_column(
        'task_templates',
        sa.Column('recur_every_n_days', sa.Integer(), nullable=True),
    )

    # ── gig_offerings ────────────────────────────────────────────────
    op.add_column(
        'gig_offerings',
        sa.Column('status', sa.String(length=16), nullable=False,
                  server_default='approved'),
    )
    op.add_column(
        'gig_offerings',
        sa.Column('review_notes', sa.Text(), nullable=True),
    )
    op.add_column(
        'gig_offerings',
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'gig_offerings',
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_gig_offerings_reviewed_by_users',
        'gig_offerings', 'users',
        ['reviewed_by'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_gig_offerings_status', 'gig_offerings', ['status'],
    )


def downgrade() -> None:
    op.drop_index('ix_gig_offerings_status', table_name='gig_offerings')
    op.drop_constraint(
        'fk_gig_offerings_reviewed_by_users', 'gig_offerings',
        type_='foreignkey',
    )
    op.drop_column('gig_offerings', 'reviewed_at')
    op.drop_column('gig_offerings', 'reviewed_by')
    op.drop_column('gig_offerings', 'review_notes')
    op.drop_column('gig_offerings', 'status')

    op.drop_column('task_templates', 'recur_every_n_days')
    op.drop_column('task_templates', 'recurrence_mode')
    op.drop_column('task_templates', 'rotation_week_of')
    op.drop_column('task_templates', 'rotation_cursor')
    op.drop_column('task_templates', 'requires_proof')
