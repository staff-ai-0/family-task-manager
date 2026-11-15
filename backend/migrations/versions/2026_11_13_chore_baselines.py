"""chore_baselines

Revision ID: chore_baselines
Revises: rules_acceptances
Create Date: 2026-11-13

Parent reference photos per chore template (show-and-tell).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "chore_baselines"
down_revision = "rules_acceptances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chore_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("family_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_url", sa.String(512), nullable=False),
        sa.Column("caption", sa.String(120), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_chore_baselines_family_id", "chore_baselines", ["family_id"])
    op.create_index("ix_chore_baselines_template_id", "chore_baselines", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_chore_baselines_template_id", table_name="chore_baselines")
    op.drop_index("ix_chore_baselines_family_id", table_name="chore_baselines")
    op.drop_table("chore_baselines")
