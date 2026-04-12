"""add_image_url_to_receipt_drafts

Revision ID: f6a7b8c9d1e2
Revises: e5f6a7b8c9d1
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d1e2"
down_revision: Union[str, None] = "e5f6a7b8c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "budget_receipt_drafts",
        sa.Column(
            "image_url",
            sa.String(500),
            nullable=True,
            comment="Stored receipt image path",
        ),
    )


def downgrade() -> None:
    op.drop_column("budget_receipt_drafts", "image_url")
