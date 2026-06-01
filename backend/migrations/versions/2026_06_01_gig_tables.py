"""gig_offerings and gig_claims tables

Revision ID: gig_tables
Revises: receipt_image_path
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'gig_tables'
down_revision = 'group_is_transfer'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    gigcategory = postgresql.ENUM(
        'chores', 'errands', 'creative', 'learning', 'outdoor', 'other',
        name='gigcategory',
        create_type=True,
    )
    gigclaimstatus = postgresql.ENUM(
        'claimed', 'completed', 'approved', 'rejected',
        name='gigclaimstatus',
        create_type=True,
    )

    op.create_table(
        'gig_offerings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('points', sa.Integer, nullable=False),
        sa.Column('difficulty', sa.Integer, nullable=False, server_default='1'),
        sa.Column('category', gigcategory, nullable=False, server_default='other'),
        sa.Column('allowed_roles', postgresql.JSONB, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('difficulty BETWEEN 1 AND 3', name='chk_gig_difficulty_range'),
        sa.CheckConstraint('points > 0', name='chk_gig_points_positive'),
    )
    op.create_index('ix_gig_offerings_family_id', 'gig_offerings', ['family_id'])
    op.create_index('ix_gig_offerings_is_active', 'gig_offerings', ['is_active'])

    op.create_table(
        'gig_claims',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('gig_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('gig_offerings.id', ondelete='CASCADE'), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('families.id', ondelete='CASCADE'), nullable=False),
        sa.Column('claimed_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', gigclaimstatus, nullable=False, server_default='claimed'),
        sa.Column('proof_text', sa.Text, nullable=True),
        sa.Column('proof_image_url', sa.String(500), nullable=True),
        sa.Column('points_awarded', sa.Integer, nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approval_notes', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_gig_claims_gig_id', 'gig_claims', ['gig_id'])
    op.create_index('ix_gig_claims_family_id', 'gig_claims', ['family_id'])
    op.create_index('ix_gig_claims_claimed_by', 'gig_claims', ['claimed_by'])
    op.create_index('ix_gig_claims_status', 'gig_claims', ['status'])
    op.create_index('ix_gig_claims_created_at', 'gig_claims', ['created_at'])
    # Partial unique: one active (non-rejected) claim per user per gig
    op.execute(
        "CREATE UNIQUE INDEX uq_gig_claim_active "
        "ON gig_claims (gig_id, claimed_by) "
        "WHERE status != 'rejected'"
    )

    # Add gig_claim_id FK to point_transactions
    op.add_column(
        'point_transactions',
        sa.Column(
            'gig_claim_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('gig_claims.id', ondelete='SET NULL'),
            nullable=True,
        )
    )

    # Data migration: copy existing is_bonus=TRUE task_templates → gig_offerings
    op.execute("""
        INSERT INTO gig_offerings (
            id, family_id, title, description, points, difficulty,
            category, allowed_roles, is_active, created_by, created_at, updated_at
        )
        SELECT
            id,
            family_id,
            title,
            description,
            GREATEST(points, 1),
            COALESCE(effort_level, 1),
            'other'::gigcategory,
            allowed_roles,
            is_active,
            created_by,
            created_at,
            updated_at
        FROM task_templates
        WHERE is_bonus = TRUE
    """)

    # Soft-delete migrated templates so they no longer appear in mandatory task views
    op.execute("""
        UPDATE task_templates
        SET is_active = FALSE
        WHERE is_bonus = TRUE
    """)


def downgrade() -> None:
    op.execute("UPDATE task_templates SET is_active = TRUE WHERE is_bonus = TRUE")
    op.drop_column('point_transactions', 'gig_claim_id')
    op.drop_table('gig_claims')
    op.drop_table('gig_offerings')
    op.execute("DROP TYPE IF EXISTS gigclaimstatus")
    op.execute("DROP TYPE IF EXISTS gigcategory")
