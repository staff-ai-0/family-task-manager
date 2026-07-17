"""Per-family gig term (gig | chamba).

Revision ID: family_gig_term
Revises: gig_payout_cadence
"""
import sqlalchemy as sa
from alembic import op

revision = "family_gig_term"
down_revision = "gig_payout_cadence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column("gig_term", sa.String(length=10), nullable=False, server_default="gig"),
    )
    op.create_check_constraint(
        "ck_families_gig_term", "families", "gig_term IN ('gig','chamba')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_families_gig_term", "families", type_="check")
    op.drop_column("families", "gig_term")
