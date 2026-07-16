"""Notification model (W3.2).

Per-user (or family-wide when user_id is null) in-app feed. Distinct from
the web-push channel — push fires at moment-of-event for live notification,
this is the persistent log/feed surfaced in the UI.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class NotificationType:
    TASK_ASSIGNED = "task_assigned"
    TASK_DUE = "task_due"
    GIG_APPROVED = "gig_approved"
    GIG_REJECTED = "gig_rejected"
    GIG_PENDING_REVIEW = "gig_pending_review"
    GIG_COMMENT = "gig_comment"
    LATE_PENALTY_APPLIED = "late_penalty_applied"
    REWARDS_LOCKED = "rewards_locked"
    REWARD_REDEEMED = "reward_redeemed"
    CALENDAR_EVENT_ADDED = "calendar_event_added"
    SHOPPING_ITEM_ADDED = "shopping_item_added"
    PET_NEEDS_ATTENTION = "pet_needs_attention"
    PET_LEVEL_UP = "pet_level_up"
    PET_EVOLVED = "pet_evolved"
    GOAL_REACHED = "goal_reached"
    MEMBER_PENDING_APPROVAL = "member_pending_approval"
    MEMBER_APPROVED = "member_approved"
    POINTS_ADJUSTED = "points_adjusted"
    # Family Bank (P1)
    PAYDAY = "payday"
    BANK_REQUEST = "bank_request"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type = Column(String(48), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=True)
    link = Column(String(512), nullable=True)
    is_read = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    read_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
