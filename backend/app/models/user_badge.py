"""UX-D2: one row per badge tier a kid has earned. Rows are never deleted or
downgraded — the count behind a badge is derived on read and can drop, the
earned tier cannot."""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class UserBadge(Base):
    __tablename__ = "user_badges"
    __table_args__ = (
        UniqueConstraint("user_id", "badge", "tier", name="uq_user_badges_user_badge_tier"),
        CheckConstraint("tier BETWEEN 1 AND 3", name="ck_user_badges_tier"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id = Column(
        UUID(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge = Column(String(32), nullable=False)   # catalog key, e.g. "chores"
    tier = Column(Integer, nullable=False)       # 1 bronze · 2 silver · 3 gold
    earned_at = Column(DateTime(timezone=True), nullable=False)
    # NULL until the unlock celebration that showed it was dismissed.
    seen_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<UserBadge(user_id={self.user_id}, badge={self.badge}, tier={self.tier})>"
