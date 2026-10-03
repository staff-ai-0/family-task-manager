"""UX-D4b mystery box.

mystery_surprises — the family's jar: short real-life surprises parents write
once ("pick dessert tonight"); reusable, picked at random.
mystery_boxes — one row per kid per PERFECT day (every non-bonus chore done).
Created closed when the kid's home reads progress; the content (a jar
surprise, or a points bonus when the jar is empty) is decided and paid once
at opening. The surprise's title is copied onto the box so a deleted jar item
still reads right.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class MysterySurprise(Base):
    __tablename__ = "mystery_surprises"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(60), nullable=False)
    emoji = Column(String(4), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class MysteryBox(Base):
    __tablename__ = "mystery_boxes"
    __table_args__ = (
        UniqueConstraint("family_id", "user_id", "day", name="uq_mystery_boxes_family_user_day"),
        CheckConstraint("kind IS NULL OR kind IN ('surprise','points')", name="ck_mystery_boxes_kind"),
        # Opened ⇔ the content is decided.
        CheckConstraint("(opened_at IS NULL) = (kind IS NULL)", name="ck_mystery_boxes_opened_iff_kind"),
        CheckConstraint("points >= 0", name="ck_mystery_boxes_points"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Date, nullable=False)                                # the perfect day (family timezone)
    kind = Column(String(16), nullable=True)                          # surprise | points, once opened
    surprise_id = Column(UUID(as_uuid=True), ForeignKey("mystery_surprises.id", ondelete="SET NULL"), nullable=True)
    surprise_title = Column(String(60), nullable=True)                # copied at opening
    surprise_emoji = Column(String(4), nullable=True)
    points = Column(Integer, nullable=False, default=0, server_default="0")
    opened_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)     # surprises only: a parent handed it over
    delivered_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
