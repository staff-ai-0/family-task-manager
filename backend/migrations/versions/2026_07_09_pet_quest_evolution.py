"""Pet quest + evolution loop

Two additions for the Joon-style pet quest/evolution loop, in ONE revision
chained off the current head (family_cup_boss_battle):

  1. kid_pets.evolution_stage — cached coarse 5-stage ladder (egg→…→adult),
     derived from cumulative xp. Backfilled from existing xp so any live pet
     lands on the correct stage immediately. The app always recomputes it from
     xp (stage_for_xp), so the column can never drift.

  2. pet_cosmetics — per-pet OWNED cosmetics (hats/colors/accessories bought
     with POINTS, equipped for free). Catalog itself is static Python data;
     this table only records ownership + equipped state, scoped to a pet
     (kid_pets is unique per user → carries family_id).

Both changes are additive and instant on PG15 (a nullable-with-default column
add → no rewrite; a new empty table). Downgrade drops both.

Revision ID: pet_quest_evolution
Revises: family_cup_boss_battle
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "pet_quest_evolution"
down_revision = "family_cup_boss_battle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kid_pets",
        sa.Column(
            "evolution_stage",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # Backfill the stage cache from existing xp (thresholds: 0/100/400/1000/2000).
    op.execute(
        """
        UPDATE kid_pets SET evolution_stage = CASE
            WHEN xp >= 2000 THEN 4
            WHEN xp >= 1000 THEN 3
            WHEN xp >= 400  THEN 2
            WHEN xp >= 100  THEN 1
            ELSE 0
        END
        """
    )

    op.create_table(
        "pet_cosmetics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "pet_id",
            UUID(as_uuid=True),
            sa.ForeignKey("kid_pets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cosmetic_key", sa.String(length=48), nullable=False),
        sa.Column(
            "equipped",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("pet_id", "cosmetic_key", name="uq_pet_cosmetic"),
    )
    op.create_index(
        "ix_pet_cosmetics_pet_id", "pet_cosmetics", ["pet_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_pet_cosmetics_pet_id", table_name="pet_cosmetics")
    op.drop_table("pet_cosmetics")
    op.drop_column("kid_pets", "evolution_stage")
