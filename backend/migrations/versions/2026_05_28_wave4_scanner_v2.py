"""wave4_scanner_v2: item rows, account card_last4, FX/IVA cols, a2a webhooks

Revision ID: wave4_scanner_v2
Revises: drop_stripe_v1
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "wave4_scanner_v2"
down_revision = "drop_stripe_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- BudgetAccount.card_last4 -------------------------------------------------
    op.add_column(
        "budget_accounts",
        sa.Column("card_last4", sa.CHAR(4), nullable=True),
    )
    op.create_index(
        "ix_budget_accounts_family_card_last4",
        "budget_accounts",
        ["family_id", "card_last4"],
        postgresql_where=sa.text("card_last4 IS NOT NULL"),
    )

    # Backfill from existing account names (e.g. "Mastercard **9222",
    # "Cheques Banamex ***313", "Tarjeta terminada en 1234"). The regex
    # requires exactly 4 trailing digits — 3-digit suffixes (e.g. "***313")
    # are intentionally NOT backfilled and the user can edit the account
    # later to set the correct last-4.
    op.execute(sa.text(
        "UPDATE budget_accounts SET card_last4 = "
        "regexp_replace(name, '.*(?:\\*{2,}|terminada en |XXXX)(\\d{4}).*', '\\1') "
        "WHERE name ~* '(\\*{2,}|terminada en |XXXX)\\d{4}' "
        "AND card_last4 IS NULL"
    ))

    # --- BudgetTransaction extra columns -----------------------------------------
    op.add_column("budget_transactions",
                  sa.Column("card_last4", sa.CHAR(4), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("iva_cents", sa.BigInteger(), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("original_amount_cents", sa.BigInteger(), nullable=True))
    op.add_column("budget_transactions",
                  sa.Column("original_currency", sa.CHAR(3), nullable=True))

    # --- budget_transaction_items ------------------------------------------------
    op.create_table(
        "budget_transaction_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("transaction_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_transactions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("qty", sa.Numeric(10, 3), nullable=True),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_categories.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bti_family_normalized_created",
                    "budget_transaction_items",
                    ["family_id", "normalized_name",
                     sa.text("created_at DESC")])
    op.create_index("ix_bti_transaction",
                    "budget_transaction_items", ["transaction_id"])
    op.create_index("ix_bti_family_category",
                    "budget_transaction_items", ["family_id", "category_id"])

    # --- family_a2a_webhooks -----------------------------------------------------
    op.create_table(
        "family_a2a_webhooks",
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # --- a2a_webhook_deliveries --------------------------------------------------
    op.create_table(
        "a2a_webhook_deliveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("family_id", UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("transaction_id", UUID(as_uuid=True),
                  sa.ForeignKey("budget_transactions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False,
                  server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_a2a_deliveries_due",
                    "a2a_webhook_deliveries",
                    ["next_retry_at"],
                    postgresql_where=sa.text("status IN ('pending', 'failed')"))
    op.create_index("ix_a2a_deliveries_family",
                    "a2a_webhook_deliveries", ["family_id"])
    op.create_index("ix_a2a_deliveries_transaction",
                    "a2a_webhook_deliveries", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_a2a_deliveries_transaction", table_name="a2a_webhook_deliveries")
    op.drop_index("ix_a2a_deliveries_family", table_name="a2a_webhook_deliveries")
    op.drop_index("ix_a2a_deliveries_due", table_name="a2a_webhook_deliveries")
    op.drop_table("a2a_webhook_deliveries")
    op.drop_table("family_a2a_webhooks")

    op.drop_index("ix_bti_family_category", table_name="budget_transaction_items")
    op.drop_index("ix_bti_transaction", table_name="budget_transaction_items")
    op.drop_index("ix_bti_family_normalized_created",
                  table_name="budget_transaction_items")
    op.drop_table("budget_transaction_items")

    op.drop_column("budget_transactions", "original_currency")
    op.drop_column("budget_transactions", "original_amount_cents")
    op.drop_column("budget_transactions", "fx_rate")
    op.drop_column("budget_transactions", "iva_cents")
    op.drop_column("budget_transactions", "card_last4")

    op.drop_index("ix_budget_accounts_family_card_last4",
                  table_name="budget_accounts")
    op.drop_column("budget_accounts", "card_last4")
