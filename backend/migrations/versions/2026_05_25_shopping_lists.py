"""shopping_lists + shopping_items tables

Revision ID: shop_v1
Revises: chore_lock_v1
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "shop_v1"
down_revision = "chore_lock_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shopping_lists",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "is_archived", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
    op.create_index(
        "ix_shopping_lists_family", "shopping_lists", ["family_id"]
    )

    op.create_table(
        "shopping_items",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "list_id",
            UUID(as_uuid=True),
            sa.ForeignKey("shopping_lists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("qty", sa.String(length=40), nullable=True),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column(
            "is_checked", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "added_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "checked_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_shopping_items_list", "shopping_items", ["list_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_shopping_items_list", table_name="shopping_items")
    op.drop_table("shopping_items")
    op.drop_index("ix_shopping_lists_family", table_name="shopping_lists")
    op.drop_table("shopping_lists")
