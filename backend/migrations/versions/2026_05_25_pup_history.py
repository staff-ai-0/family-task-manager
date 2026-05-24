"""pup_score_snapshots table (W6.3)

Revision ID: pup_hist_v1
Revises: frankie_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "pup_hist_v1"
down_revision = "frankie_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pup_score_snapshots",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=16), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_pup_family_date",
        "pup_score_snapshots",
        ["family_id", "snapshot_date"],
    )
    op.create_index(
        "ix_pup_family_date",
        "pup_score_snapshots",
        ["family_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_pup_family_date", table_name="pup_score_snapshots")
    op.drop_constraint("uq_pup_family_date", "pup_score_snapshots", type_="unique")
    op.drop_table("pup_score_snapshots")
