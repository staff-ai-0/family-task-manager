"""KidPet model (W4.3).

One virtual pet per user. Stats:
- mood   0..100  drops when neglected
- hunger 0..100  RISES with time, drops when fed (100=starving, 0=full)
- xp     >=0     grows when the owner completes tasks

Level is derived: floor(sqrt(xp / 100)). Decay handled by the daily
scheduler that already runs the overdue sweep.
"""

import math
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


VALID_SPECIES = {"cat", "dog", "dragon", "fox", "owl", "bunny"}


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

    last_decay_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    def status_label(self) -> str:
        if self.hunger >= 80:
            return "starving"
        if self.mood <= 20:
            return "sad"
        if self.mood >= 80 and self.hunger <= 30:
            return "happy"
        return "ok"
