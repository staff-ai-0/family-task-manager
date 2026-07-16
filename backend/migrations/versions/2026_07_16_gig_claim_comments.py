"""Gig-claim comment threads (parent ↔ kid conversation on a claim).

Revision ID: gig_claim_comments
Revises: usd_price_alignment
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "gig_claim_comments"
down_revision = "usd_price_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gig_claim_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "claim_id",
            UUID(as_uuid=True),
            sa.ForeignKey("gig_claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gig_claim_comments_claim", "gig_claim_comments", ["claim_id"])
    op.create_index("ix_gig_claim_comments_family", "gig_claim_comments", ["family_id"])


def downgrade() -> None:
    op.drop_index("ix_gig_claim_comments_family", table_name="gig_claim_comments")
    op.drop_index("ix_gig_claim_comments_claim", table_name="gig_claim_comments")
    op.drop_table("gig_claim_comments")
