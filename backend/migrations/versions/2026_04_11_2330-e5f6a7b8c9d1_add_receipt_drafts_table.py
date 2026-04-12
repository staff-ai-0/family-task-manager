"""add_receipt_drafts_table

Revision ID: e5f6a7b8c9d1
Revises: d4e5f6a7b8c1
Create Date: 2026-04-11 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d1"
down_revision: Union[str, None] = "d4e5f6a7b8c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_receipt_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scanned_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Extracted receipt fields: date, total_amount, payee_name, items, currency",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.0",
            comment="Vision model confidence 0.0–1.0",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending | approved | rejected",
        ),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("budget_transactions.id", ondelete="SET NULL"),
            nullable=True,
            comment="Populated on approval",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_budget_receipt_drafts_family_id",
        "budget_receipt_drafts",
        ["family_id"],
    )
    op.create_index(
        "ix_budget_receipt_drafts_status",
        "budget_receipt_drafts",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_receipt_drafts_status", table_name="budget_receipt_drafts")
    op.drop_index("ix_budget_receipt_drafts_family_id", table_name="budget_receipt_drafts")
    op.drop_table("budget_receipt_drafts")
