"""payout_receipts — bank-transfer receipts that paid a chore paycheck

Revision ID: payout_receipts
Revises: mystery_box
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "payout_receipts"
down_revision = "mystery_box"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payout_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("folio", sa.String(40), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("concept", sa.Text(), nullable=True),
        sa.Column("weeks", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("family_id", "folio", name="uq_payout_receipts_family_folio"),
    )
    op.create_index("ix_payout_receipts_family_id", "payout_receipts", ["family_id"])
    op.create_index("ix_payout_receipts_user_id", "payout_receipts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_payout_receipts_user_id", table_name="payout_receipts")
    op.drop_index("ix_payout_receipts_family_id", table_name="payout_receipts")
    op.drop_table("payout_receipts")
