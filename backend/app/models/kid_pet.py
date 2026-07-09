"""KidPet model (W4.3 · quest/evolution loop 2026-07-09).

One virtual pet per user. Stats:
- mood   0..100  drops when neglected
- hunger 0..100  RISES with time, drops when fed (100=starving, 0=full)
- xp     >=0     grows when the owner's task/gig assignment is APPROVED

Two long-horizon progression ladders derived from cumulative ``xp`` (the
Joon-style antidote to weeks 4-8 novelty decay):

- ``level``           — a fine-grained sqrt curve (floor(sqrt(xp/100))). Unbounded.
- ``evolution_stage`` — a coarse 5-stage ladder (egg→baby→kid→teen→adult),
  gated on xp thresholds. Stored on the row (cheap cosmetic-unlock queries +
  robust crossing detection) but ALWAYS recomputed from xp, so it can never
  drift. Cosmetics unlock per stage.

Decay is handled by the daily scheduler that already runs the overdue sweep.
"""

import math
import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


VALID_SPECIES = {"cat", "dog", "dragon", "fox", "owl", "bunny"}


# ── Evolution ladder ────────────────────────────────────────────────
# 5 stages. EVOLUTION_XP_THRESHOLDS[i] = cumulative xp required to REACH
# stage i. stage_for_xp() is the single source of truth; the stored
# ``evolution_stage`` column is only ever a cache of it.
EVOLUTION_STAGE_NAMES = ["egg", "baby", "kid", "teen", "adult"]
EVOLUTION_XP_THRESHOLDS = [0, 100, 400, 1000, 2000]
MAX_EVOLUTION_STAGE = len(EVOLUTION_STAGE_NAMES) - 1  # 4 (adult)

# Bilingual display labels (Mexico-first) for notifications / UI copy.
EVOLUTION_STAGE_LABELS = {
    0: {"es": "huevo", "en": "egg"},
    1: {"es": "bebé", "en": "baby"},
    2: {"es": "pequeño", "en": "kid"},
    3: {"es": "joven", "en": "teen"},
    4: {"es": "adulto", "en": "adult"},
}


def stage_for_xp(xp: int) -> int:
    """Highest evolution-stage index whose xp threshold is met by ``xp``."""
    stage = 0
    for i, threshold in enumerate(EVOLUTION_XP_THRESHOLDS):
        if (xp or 0) >= threshold:
            stage = i
    return stage


class KidPet(Base):
    __tablename__ = "kid_pets"
    __table_args__ = (
        CheckConstraint(
            "mood BETWEEN 0 AND 100 AND hunger BETWEEN 0 AND 100 AND xp >= 0",
            name="chk_pet_stats",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name = Column(String(40), nullable=False)
    species = Column(String(24), nullable=False, default="cat", server_default="cat")

    mood = Column(Integer, nullable=False, default=80, server_default="80")
    hunger = Column(Integer, nullable=False, default=50, server_default="50")
    xp = Column(Integer, nullable=False, default=0, server_default="0")

    # Coarse 5-stage evolution ladder, cached from xp (see stage_for_xp).
    # Recomputed on every xp change — never authored directly.
    evolution_stage = Column(
        Integer, nullable=False, default=0, server_default="0"
    )

    last_decay_at = Column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    @property
    def level(self) -> int:
        return int(math.sqrt(max(0, self.xp) / 100.0))

    @property
    def xp_to_next_level(self) -> int:
        next_lvl = self.level + 1
        return next_lvl * next_lvl * 100

    @property
    def evolution_stage_name(self) -> str:
        idx = min(max(self.evolution_stage or 0, 0), MAX_EVOLUTION_STAGE)
        return EVOLUTION_STAGE_NAMES[idx]

    @property
    def xp_to_next_stage(self) -> Optional[int]:
        """Cumulative xp needed to reach the next stage, or None if maxed."""
        stage = stage_for_xp(self.xp)
        if stage >= MAX_EVOLUTION_STAGE:
            return None
        return EVOLUTION_XP_THRESHOLDS[stage + 1]

    @property
    def status_label(self) -> str:
        if self.hunger >= 80:
            return "starving"
        if self.mood <= 20:
            return "sad"
        if self.mood >= 80 and self.hunger <= 30:
            return "happy"
        return "ok"
