"""Referral program: families.referral_code + referrals table

Give-a-month/get-a-month growth loop, in ONE revision chained off the
current head (pet_quest_evolution):

  1. families.referral_code — stable public referral code (unique, nullable).
     Backfilled with a unique code for every existing family so live families
     have a shareable link immediately; new families generate one on demand
     (ReferralService.get_or_create_referral_code).

  2. referrals — one row per referrer_family → referred_family link, with a
     reward_granted_at bookkeeping timestamp. referred_family_id is UNIQUE
     (a family can be referred only once — the authoritative double-credit
     guard). Both FKs cascade on family delete.

Additive on PG15: a nullable column add (no rewrite) + a backfill UPDATE +
a new empty table. Downgrade drops both.

Revision ID: referral_program
Revises: pet_quest_evolution
Create Date: 2026-07-09
"""
import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "referral_program"
down_revision = "pet_quest_evolution"
branch_labels = None
depends_on = None


_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def upgrade() -> None:
    # 1. Add the column (nullable, no unique index yet so the backfill is free
    #    to run before uniqueness is enforced).
    op.add_column(
        "families",
        sa.Column("referral_code", sa.String(length=16), nullable=True),
    )

    # 2. Backfill a unique code for every existing family.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM families WHERE referral_code IS NULL")
    ).fetchall()
    used: set[str] = set()
    for (family_id,) in rows:
        code = _generate_code()
        while code in used:
            code = _generate_code()
        used.add(code)
        conn.execute(
            sa.text(
                "UPDATE families SET referral_code = :code WHERE id = :id"
            ),
            {"code": code, "id": family_id},
        )

    # 3. Enforce uniqueness. A single unique index matches the ORM column's
    #    (unique=True, index=True). Multiple NULLs remain allowed in PG.
    op.create_index(
        "ix_families_referral_code",
        "families",
        ["referral_code"],
        unique=True,
    )

    # 4. Referrals table.
    op.create_table(
        "referrals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "referrer_family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "referred_family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reward_granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # A family can be the referred party at most once.
        sa.UniqueConstraint(
            "referred_family_id", name="uq_referrals_referred_family"
        ),
    )
    op.create_index(
        "ix_referrals_referrer_family_id",
        "referrals",
        ["referrer_family_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_referrals_referrer_family_id", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("ix_families_referral_code", table_name="families")
    op.drop_column("families", "referral_code")
