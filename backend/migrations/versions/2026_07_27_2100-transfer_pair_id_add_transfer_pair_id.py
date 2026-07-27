"""add transfer_pair_id to budget_transactions

Account transfers write two legs, but nothing linked them: transfer_account_id
is a FK to an ACCOUNT, not to the sibling row. Deleting or editing one leg
therefore left the other behind and silently unbalanced the family's books
(verified: deleting a withdrawal leg moved total on-budget balance 0 -> 10000).

This column carries a shared id on both legs so the pair can be found and
handled atomically. Nullable: pre-existing transfers have no pair id, and the
delete path falls back to leaving unpaired legs alone rather than guessing.

Revision ID: transfer_pair_id
Revises: user_last_seen_at
Create Date: 2026-07-27 21:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'transfer_pair_id'
down_revision = 'user_last_seen_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'budget_transactions',
        sa.Column(
            'transfer_pair_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment=(
                'Shared id joining the two legs of an account transfer. '
                'transfer_account_id points at the ACCOUNT, so before this '
                'column existed nothing could find a leg\'s sibling — deleting '
                'or editing one leg silently unbalanced the family\'s books.'
            ),
        ),
    )
    op.create_index(
        'ix_budget_transactions_transfer_pair_id',
        'budget_transactions',
        ['transfer_pair_id'],
    )

    # Backfill existing pairs: legs are mirror images — same family and date,
    # opposite amounts, and each one's account is the other's transfer target.
    # Only pair rows that match exactly one counterpart, so ambiguous
    # same-day/same-amount transfers are left unpaired rather than mis-joined.
    op.execute("""
        WITH candidates AS (
            SELECT w.id AS withdrawal_id,
                   d.id AS deposit_id,
                   COUNT(*) OVER (PARTITION BY w.id) AS w_matches,
                   COUNT(*) OVER (PARTITION BY d.id) AS d_matches
            FROM budget_transactions w
            JOIN budget_transactions d
              ON d.family_id = w.family_id
             AND d.date = w.date
             AND d.amount = -w.amount
             AND d.account_id = w.transfer_account_id
             AND w.account_id = d.transfer_account_id
             AND d.id <> w.id
            WHERE w.amount < 0
              AND w.transfer_account_id IS NOT NULL
              AND d.transfer_account_id IS NOT NULL
              AND w.deleted_at IS NULL
              AND d.deleted_at IS NULL
        ),
        unique_pairs AS (
            SELECT withdrawal_id, deposit_id
            FROM candidates
            WHERE w_matches = 1 AND d_matches = 1
        )
        UPDATE budget_transactions t
        SET transfer_pair_id = gen_random_uuid_pair.pair_id
        FROM (
            SELECT withdrawal_id, deposit_id, gen_random_uuid() AS pair_id
            FROM unique_pairs
        ) AS gen_random_uuid_pair
        WHERE t.id IN (gen_random_uuid_pair.withdrawal_id,
                       gen_random_uuid_pair.deposit_id)
    """)


def downgrade() -> None:
    op.drop_index(
        'ix_budget_transactions_transfer_pair_id',
        table_name='budget_transactions',
    )
    op.drop_column('budget_transactions', 'transfer_pair_id')
