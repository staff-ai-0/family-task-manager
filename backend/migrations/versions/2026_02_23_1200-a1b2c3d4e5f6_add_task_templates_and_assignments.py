"""add task templates and assignments

Revision ID: a1b2c3d4e5f6
Revises: 0bf3ae3793da
Create Date: 2026-02-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '0bf3ae3793da'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create task_templates table
    op.create_table('task_templates',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('points', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('interval_days', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_bonus', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('family_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['family_id'], ['families.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_task_templates_id'), 'task_templates', ['id'], unique=False)
    op.create_index(op.f('ix_task_templates_family_id'), 'task_templates', ['family_id'], unique=False)
    op.create_index(op.f('ix_task_templates_is_active'), 'task_templates', ['is_active'], unique=False)

    # Create assignmentstatus enum
    assignmentstatus_enum = postgresql.ENUM(
        'pending', 'completed', 'overdue', 'cancelled',
        name='assignmentstatus',
        create_type=False,
    )
    assignmentstatus_enum.create(op.get_bind(), checkfirst=True)

    # Create task_assignments table
    op.create_table('task_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('template_id', sa.UUID(), nullable=False),
        sa.Column('assigned_to', sa.UUID(), nullable=False),
        sa.Column('family_id', sa.UUID(), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'completed', 'overdue', 'cancelled', name='assignmentstatus', create_type=False), nullable=False, server_default='pending'),
        sa.Column('assigned_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('week_of', sa.Date(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['task_templates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['family_id'], ['families.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_task_assignments_id'), 'task_assignments', ['id'], unique=False)
    op.create_index(op.f('ix_task_assignments_template_id'), 'task_assignments', ['template_id'], unique=False)
    op.create_index(op.f('ix_task_assignments_assigned_to'), 'task_assignments', ['assigned_to'], unique=False)
    op.create_index(op.f('ix_task_assignments_family_id'), 'task_assignments', ['family_id'], unique=False)
    op.create_index(op.f('ix_task_assignments_status'), 'task_assignments', ['status'], unique=False)
    op.create_index(op.f('ix_task_assignments_week_of'), 'task_assignments', ['week_of'], unique=False)

    # Add assignment_id column to point_transactions
    op.add_column('point_transactions',
        sa.Column('assignment_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_point_transactions_assignment_id',
        'point_transactions', 'task_assignments',
        ['assignment_id'], ['id'],
        ondelete='SET NULL',
    )

    # Add triggered_by_assignment_id column to consequences
    op.add_column('consequences',
        sa.Column('triggered_by_assignment_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_consequences_triggered_by_assignment_id',
        'consequences', 'task_assignments',
        ['triggered_by_assignment_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # Drop FK and column from consequences
    op.drop_constraint('fk_consequences_triggered_by_assignment_id', 'consequences', type_='foreignkey')
    op.drop_column('consequences', 'triggered_by_assignment_id')

    # Drop FK and column from point_transactions
    op.drop_constraint('fk_point_transactions_assignment_id', 'point_transactions', type_='foreignkey')
    op.drop_column('point_transactions', 'assignment_id')

    # Drop task_assignments table
    op.drop_index(op.f('ix_task_assignments_week_of'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_status'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_family_id'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_assigned_to'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_template_id'), table_name='task_assignments')
    op.drop_index(op.f('ix_task_assignments_id'), table_name='task_assignments')
    op.drop_table('task_assignments')

    # Drop enum
    sa.Enum(name='assignmentstatus').drop(op.get_bind(), checkfirst=True)

    # Drop task_templates table
    op.drop_index(op.f('ix_task_templates_is_active'), table_name='task_templates')
    op.drop_index(op.f('ix_task_templates_family_id'), table_name='task_templates')
    op.drop_index(op.f('ix_task_templates_id'), table_name='task_templates')
    op.drop_table('task_templates')
