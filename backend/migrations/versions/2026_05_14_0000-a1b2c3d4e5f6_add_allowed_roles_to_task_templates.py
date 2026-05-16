"""add_allowed_roles_to_task_templates

Revision ID: a1c4d5e6f7b9
Revises: f6a7b8c9d1e2
Create Date: 2026-05-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a1c4d5e6f7b9"
down_revision = "f6a7b8c9d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_templates",
        sa.Column(
            "allowed_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="List of role strings (parent/teen/child) eligible under AUTO. Null = all roles allowed.",
        ),
    )


def downgrade() -> None:
    op.drop_column("task_templates", "allowed_roles")
