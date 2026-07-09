"""Family Cup seasons + chat image attachments (P2)

Two additions for the Family Cup + cooperative boss battle + auto-post feature,
in ONE revision chained off the current head (ops_indexes_soft_delete):

  1. family_cup_seasons — persists the winner of each *closed* weekly Family Cup
     season (one row per family + week_start). Denormalizes the winner name +
     points so the record survives the winner's deletion. The live leaderboard
     is computed on the fly from point_transactions; this is history only.

  2. family_chat_messages.image_url — nullable column so auto-posted task/gig
     completions can carry the proof photo when one is present. Reactions
     already work on any family_chat row, so the auto-posted card is
     reaction-ready with no further schema.

Both changes are additive and instant on PG15 (new empty table + a nullable
column with no default → no table rewrite, no backfill). Downgrade drops both.

Revision ID: family_cup_boss_battle
Revises: ops_indexes_soft_delete
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "family_cup_boss_battle"
down_revision = "ops_indexes_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "family_cup_seasons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "winner_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("winner_name", sa.String(length=120), nullable=True),
        sa.Column(
            "winner_points", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "family_id", "week_start", name="uq_family_cup_family_week"
        ),
    )
    op.create_index(
        "ix_family_cup_seasons_family_id",
        "family_cup_seasons",
        ["family_id"],
        unique=False,
    )

    op.add_column(
        "family_chat_messages",
        sa.Column("image_url", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("family_chat_messages", "image_url")
    op.drop_index(
        "ix_family_cup_seasons_family_id", table_name="family_cup_seasons"
    )
    op.drop_table("family_cup_seasons")
