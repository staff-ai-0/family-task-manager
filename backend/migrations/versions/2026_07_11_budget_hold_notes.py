"""Hold-for-next-month + category notes.

Revision ID: budget_hold_notes
Revises: budget_parity
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "budget_hold_notes"
down_revision = "budget_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_month_holds",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id", UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("family_id", "month", name="uq_month_hold_family_month"),
    )
    op.add_column(
        "budget_categories",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("budget_categories", "notes")
    op.drop_table("budget_month_holds")
