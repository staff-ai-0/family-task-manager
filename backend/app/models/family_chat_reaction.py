"""Family chat reaction model (W8.6).

One row per (message, user, emoji). UNIQUE prevents duplicate reactions
from the same user; toggling re-adds is a no-op via insert-on-conflict.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class FamilyChatReaction(Base):
    __tablename__ = "family_chat_reactions"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "user_id", "emoji", name="uq_chat_react_unique"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("family_chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji = Column(String(16), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
