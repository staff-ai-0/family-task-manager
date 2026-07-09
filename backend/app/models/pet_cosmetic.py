"""PetCosmetic model (pet quest/evolution loop, 2026-07-09).

Per-pet OWNED cosmetic. A kid buys a cosmetic with POINTS (the privileges
currency — never cash); equipping is free. The catalog itself is static
Python data (app/services/pet_cosmetics.py) — this table only records which
catalog entries a given pet owns and which one is equipped per slot.

Scoping: a cosmetic belongs to exactly one pet (``pet_id`` → kid_pets, which
is unique per user, which carries family_id). All service queries filter by
the acting user's own pet, so isolation is structural.
"""

import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PetCosmetic(Base):
    __tablename__ = "pet_cosmetics"
    __table_args__ = (
        UniqueConstraint("pet_id", "cosmetic_key", name="uq_pet_cosmetic"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    pet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("kid_pets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Key into the static COSMETICS catalog (app/services/pet_cosmetics.py).
    cosmetic_key = Column(String(48), nullable=False)
    # At most one equipped cosmetic per slot per pet (enforced in the service).
    equipped = Column(Boolean, nullable=False, default=False, server_default="false")
    acquired_at = Column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
