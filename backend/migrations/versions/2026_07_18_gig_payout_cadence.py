"""Gig payout cadence — advisory payout rhythm on gig offerings.

Revision ID: gig_payout_cadence
Revises: naive_to_timestamptz
"""
import sqlalchemy as sa
from alembic import op

revision = "gig_payout_cadence"
down_revision = "naive_to_timestamptz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gig_offerings",
        sa.Column(
            "payout_cadence",
            sa.String(length=10),
            nullable=False,
            server_default="immediate",
        ),
    )
    op.create_check_constraint(
        "ck_gig_offerings_payout_cadence",
        "gig_offerings",
        "payout_cadence IN ('immediate','weekly','biweekly','monthly')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_gig_offerings_payout_cadence", "gig_offerings", type_="check"
    )
    op.drop_column("gig_offerings", "payout_cadence")
