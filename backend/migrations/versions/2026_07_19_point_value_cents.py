"""Family-set point value (centavos) for the points_rate allowance mode.

Revision ID: point_value_cents
Revises: completion_grade
"""
import sqlalchemy as sa
from alembic import op

revision = "point_value_cents"
down_revision = "completion_grade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column(
            "point_value_cents", sa.Integer(), nullable=False, server_default="100"
        ),
    )
    op.create_check_constraint(
        "ck_families_point_value_cents", "families", "point_value_cents > 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_families_point_value_cents", "families", type_="check")
    op.drop_column("families", "point_value_cents")
