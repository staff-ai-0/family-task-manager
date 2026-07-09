"""Family chat message (W8.1).

Single shared thread per family. Anyone in the family can post + read.
Kept simple — no DMs, no threads, no editing. Designed for quick "I'm
home" / "running late" / "grab milk" pings.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class FamilyChatMessage(Base):
    __tablename__ = "family_chat_messages"

    # Hot path: chat thread is paged `WHERE family_id = ? ORDER BY created_at`.
    # Composite (family_id, created_at) serves filter + order in one scan.
    # Mirrors the ops migration.
    __table_args__ = (
        Index(
            "ix_family_chat_messages_family_created",
            "family_id",
            "created_at",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    body = Column(Text, nullable=False)
    # Optional attachment (auto-posted task/gig completions carry the proof
    # photo here when one is present). Nullable — normal chat pings have none.
    image_url = Column(String(512), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
