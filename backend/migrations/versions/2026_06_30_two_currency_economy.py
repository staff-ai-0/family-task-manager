"""two-currency economy: cash_cents + cash_transactions; drop mandatory-zero-points check

Revision ID: two_currency_economy
Revises: mcp_restricted_role
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "two_currency_economy"
down_revision = "mcp_restricted_role"
branch_labels = None
depends_on = None


def upgrade():
    # 1. User cash balance (centavos).
    op.add_column(
        "users",
        sa.Column("cash_cents", sa.Integer(), nullable=False, server_default="0"),
    )

    # 2. Cash transaction type enum. Labels MUST be the UPPERCASE member NAMES:
    #    SQLEnum(CashTransactionType) has no values_callable, so SQLAlchemy binds
    #    the enum NAME ("GIG_EARNED"), not the value ("gig_earned"). This matches
    #    the existing transactiontype enum convention (see the 2026_05_22 migration).
    #    create_type=False so create_table below does not create it a second time.
    cash_type = postgresql.ENUM(
        "GIG_EARNED", "PAYOUT", "ADJUSTMENT",
        name="cashtransactiontype", create_type=False,
    )
    cash_type.create(op.get_bind(), checkfirst=True)

    # 3. cash_transactions ledger.
    op.create_table(
        "cash_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", cash_type, nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("balance_before", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column(
            "assignment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("task_assignments.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "gig_claim_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("gig_claims.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_cash_transactions_user_id", "cash_transactions", ["user_id"])
    op.create_index("ix_cash_transactions_family_id", "cash_transactions", ["family_id"])
    op.create_index("ix_cash_transactions_type", "cash_transactions", ["type"])
    op.create_index("ix_cash_transactions_created_at", "cash_transactions", ["created_at"])

    # 4. Drop the mandatory-zero-points CHECK — chores now award points too.
    #    IF EXISTS guards a DB that never had it (create_all-provisioned).
    op.execute(
        "ALTER TABLE task_templates DROP CONSTRAINT IF EXISTS chk_mandatory_zero_points"
    )


def downgrade():
    # Re-add the old constraint as NOT VALID: by the time this feature ships,
    # mandatory templates carry points>0, so a validating CHECK would abort the
    # downgrade. NOT VALID restores the forward guard (new mandatory rows must be
    # zero) without failing on the existing points-bearing rows.
    op.execute(
        "ALTER TABLE task_templates ADD CONSTRAINT chk_mandatory_zero_points "
        "CHECK (is_bonus = true OR points = 0) NOT VALID"
    )
    op.drop_index("ix_cash_transactions_created_at", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_type", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_family_id", table_name="cash_transactions")
    op.drop_index("ix_cash_transactions_user_id", table_name="cash_transactions")
    op.drop_table("cash_transactions")
    postgresql.ENUM(name="cashtransactiontype").drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "cash_cents")
