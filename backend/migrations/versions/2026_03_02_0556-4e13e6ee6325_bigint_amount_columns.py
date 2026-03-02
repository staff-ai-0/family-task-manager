"""bigint_amount_columns

Revision ID: 4e13e6ee6325
Revises: add_starting_balance_v1
Create Date: 2026-03-02 05:56:08.284381

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4e13e6ee6325'
down_revision = 'add_starting_balance_v1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix assignmenttype enum to use lowercase values (matching Python enum .value)
    # The enum was created with uppercase names ('AUTO','FIXED','ROTATE') instead of
    # lowercase values ('auto','fixed','rotate'), causing a DEFAULT 'auto' mismatch.
    op.execute("ALTER TYPE assignmenttype RENAME TO assignmenttype_old")
    op.execute("CREATE TYPE assignmenttype AS ENUM ('auto', 'fixed', 'rotate')")
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type "
        "TYPE assignmenttype USING (lower(assignment_type::text))::assignmenttype"
    )
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type "
        "SET DEFAULT 'auto'::assignmenttype"
    )
    op.execute("DROP TYPE assignmenttype_old")

    # Upgrade money columns from INTEGER to BIGINT to support large amounts (e.g. $23M+)
    op.alter_column('budget_accounts', 'starting_balance',
               existing_type=sa.INTEGER(),
               server_default=None,
               type_=sa.BigInteger(),
               existing_comment='Initial account balance in cents at creation time',
               existing_nullable=False)
    op.alter_column('budget_allocations', 'budgeted_amount',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_comment='Amount in cents',
               existing_nullable=False)
    op.alter_column('budget_categories', 'goal_amount',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_comment='Monthly goal in cents',
               existing_nullable=False)
    op.alter_column('budget_recurring_transactions', 'amount',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_comment='Amount in cents (negative=expense, positive=income)',
               existing_nullable=False)
    op.alter_column('budget_transactions', 'amount',
               existing_type=sa.INTEGER(),
               type_=sa.BigInteger(),
               existing_comment='Amount in cents (negative=expense, positive=income)',
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('budget_transactions', 'amount',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_comment='Amount in cents (negative=expense, positive=income)',
               existing_nullable=False)
    op.alter_column('budget_recurring_transactions', 'amount',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_comment='Amount in cents (negative=expense, positive=income)',
               existing_nullable=False)
    op.alter_column('budget_categories', 'goal_amount',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_comment='Monthly goal in cents',
               existing_nullable=False)
    op.alter_column('budget_allocations', 'budgeted_amount',
               existing_type=sa.BigInteger(),
               type_=sa.INTEGER(),
               existing_comment='Amount in cents',
               existing_nullable=False)
    op.alter_column('budget_accounts', 'starting_balance',
               existing_type=sa.BigInteger(),
               server_default=sa.text('0'),
               type_=sa.INTEGER(),
               existing_comment='Initial account balance in cents at creation time',
               existing_nullable=False)

    # Downgrade assignmenttype back to uppercase (not recommended)
    op.execute("ALTER TYPE assignmenttype RENAME TO assignmenttype_old")
    op.execute("CREATE TYPE assignmenttype AS ENUM ('AUTO', 'FIXED', 'ROTATE')")
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type DROP DEFAULT"
    )
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type "
        "TYPE assignmenttype USING (upper(assignment_type::text))::assignmenttype"
    )
    op.execute(
        "ALTER TABLE task_templates ALTER COLUMN assignment_type "
        "SET DEFAULT 'AUTO'::assignmenttype"
    )
    op.execute("DROP TYPE assignmenttype_old")

