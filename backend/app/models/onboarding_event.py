"""OnboardingEvent — funnel events for the welcome tour + onboarding.

One row per event (tour started / completed / skipped / replayed) so the parent
can see whether new family members actually finish onboarding, not just whether
they were shown it (that's the boolean users.completed_welcome_tour flag).
"""
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid

from app.core.database import Base

# Recognized event types. Kept as plain strings (not a DB enum) so adding a new
# event never needs a migration; the route validates against this set.
ONBOARDING_EVENT_TYPES = frozenset(
    {"tour_started", "tour_completed", "tour_skipped", "tour_replayed"}
)


class OnboardingEvent(Base):
    __tablename__ = "onboarding_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(40), nullable=False)
    step_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
