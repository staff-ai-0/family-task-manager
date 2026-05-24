"""kid_pets table (W4.3)

Revision ID: pet_v1
Revises: gig_mode_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "pet_v1"
down_revision = "gig_mode_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kid_pets",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column(
            "species", sa.String(length=24), nullable=False, server_default="cat"
        ),
        sa.Column("mood", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("hunger", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "last_decay_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_check_constraint(
        "chk_pet_stats", "kid_pets",
        "mood BETWEEN 0 AND 100 AND hunger BETWEEN 0 AND 100 AND xp >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("chk_pet_stats", "kid_pets", type_="check")
    op.drop_table("kid_pets")
