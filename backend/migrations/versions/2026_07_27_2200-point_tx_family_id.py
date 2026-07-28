"""add family_id to point_transactions

The points ledger was the one family-data table without a family_id, so every
aggregate (PointsService.get_total_earned/get_total_spent, the reward
redemption count) scoped by user_id alone. That was only safe because callers
happened to resolve the user through get_family_user first — tenancy rested on
caller discipline instead of the schema.

Backfill is exact and total: users.family_id is NOT NULL and point_transactions
.user_id is a NOT NULL FK with ON DELETE CASCADE, so every row has exactly one
owning user and therefore exactly one family. That is why the column can be
flipped to NOT NULL in the same revision.

Revision ID: point_tx_family_id
Revises: transfer_pair_id
Create Date: 2026-07-27 22:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'point_tx_family_id'
down_revision = 'transfer_pair_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'point_transactions',
        sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.execute("""
        UPDATE point_transactions pt
        SET family_id = u.family_id
        FROM users u
        WHERE u.id = pt.user_id
          AND pt.family_id IS NULL
    """)

    op.alter_column('point_transactions', 'family_id', nullable=False)
    op.create_index(
        'ix_point_transactions_family_id', 'point_transactions', ['family_id']
    )
    op.create_foreign_key(
        'fk_point_transactions_family_id_families',
        'point_transactions', 'families',
        ['family_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_point_transactions_family_id_families',
        'point_transactions',
        type_='foreignkey',
    )
    op.drop_index(
        'ix_point_transactions_family_id', table_name='point_transactions'
    )
    op.drop_column('point_transactions', 'family_id')
