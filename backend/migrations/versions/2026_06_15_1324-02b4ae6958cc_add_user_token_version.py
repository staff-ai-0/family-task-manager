"""add user token_version

Revision ID: 02b4ae6958cc
Revises: 7a3b284cde5a
Create Date: 2026-06-15 13:24:03.241225

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '02b4ae6958cc'
down_revision = '7a3b284cde5a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
