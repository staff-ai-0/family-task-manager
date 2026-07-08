"""Family Bank (P1-W1): kid_bank_accounts + cash_transactions.jar + enum values

Adds, in ONE revision:
  1. kid_bank_accounts — per-kid jar balances (spend/save/share, centavos) +
     parent config (allowance, %-split, interest bps, match, approval toggle),
     with the split-sum and range CHECK constraints and a family_id index.
  2. cash_transactions.jar — VARCHAR(8) NOT NULL DEFAULT 'spend'. Instant on
     PG15 (non-volatile default), no backfill: historically all cash was
     spendable, so 'spend' is the correct attribution for every legacy row.
  3. Four new cashtransactiontype enum values. ⚠️ SQLEnum(CashTransactionType)
     has NO values_callable, so the PG enum stores the UPPERCASE MEMBER NAMES
     (verified live: GIG_EARNED, PAYOUT, ADJUSTMENT). We ADD the names, not the
     lowercase values. PG15 permits ADD VALUE inside the migration transaction
     because this migration does not itself USE the new values.
  4. Flips family_bank_automation = true on the plus/pro plan rows (all
     currency variants) so the credit-time splitter + payday sweep are entitled
     in prod without a manual follow-up. Idempotent (jsonb_set).

Downgrade drops the table + column but LEAVES the enum values in place —
PostgreSQL cannot drop enum values.

Revision ID: family_bank_w1
Revises: mxn_plan_currency_w6
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "family_bank_w1"
down_revision = "mxn_plan_currency_w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Per-kid Family Bank account.
    op.create_table(
        "kid_bank_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("spend_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("save_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("share_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allowance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payday_weekday", sa.SmallInteger(), nullable=False, server_default="6"),
        sa.Column("split_spend_pct", sa.SmallInteger(), nullable=False, server_default="100"),
        sa.Column("split_save_pct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("split_share_pct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("interest_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("match_pct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("match_cap_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "save_withdrawal_requires_approval", sa.Boolean(),
            nullable=False, server_default="true",
        ),
        sa.Column("last_payday_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "split_spend_pct + split_save_pct + split_share_pct = 100",
            name="ck_kid_bank_split_sum",
        ),
        sa.CheckConstraint(
            "spend_cents >= 0 AND save_cents >= 0 AND share_cents >= 0 "
            "AND allowance_cents >= 0 "
            "AND payday_weekday BETWEEN 0 AND 6 "
            "AND split_spend_pct BETWEEN 0 AND 100 "
            "AND split_save_pct BETWEEN 0 AND 100 "
            "AND split_share_pct BETWEEN 0 AND 100 "
            "AND interest_rate_bps BETWEEN 0 AND 10000 "
            "AND match_pct BETWEEN 0 AND 200 "
            "AND match_cap_cents >= 0",
            name="ck_kid_bank_ranges",
        ),
    )
    op.create_index(
        "ix_kid_bank_accounts_family_id", "kid_bank_accounts", ["family_id"]
    )

    # 2. Jar attribution on the existing ledger.
    op.add_column(
        "cash_transactions",
        sa.Column("jar", sa.String(8), nullable=False, server_default="spend"),
    )

    # 3. New ledger types — UPPERCASE member names (see docstring).
    for name in ("ALLOWANCE", "INTEREST", "MATCH", "JAR_TRANSFER"):
        op.execute(
            f"ALTER TYPE cashtransactiontype ADD VALUE IF NOT EXISTS '{name}'"
        )

    # 4. Entitle the paid tiers to Family Bank automation (all currency rows).
    op.execute(
        "UPDATE subscription_plans "
        "SET limits = jsonb_set("
        "  COALESCE(limits, '{}'::jsonb), '{family_bank_automation}', 'true'::jsonb, true"
        "), updated_at = now() "
        "WHERE name IN ('plus', 'pro')"
    )


def downgrade() -> None:
    # Enum values cannot be dropped in PostgreSQL — they persist. The jar
    # attribution + jar table go away; ADD VALUE'd labels remain harmless.
    op.drop_index("ix_kid_bank_accounts_family_id", table_name="kid_bank_accounts")
    op.drop_table("kid_bank_accounts")
    op.drop_column("cash_transactions", "jar")
