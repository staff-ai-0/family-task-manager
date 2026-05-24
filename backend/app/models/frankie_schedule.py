"""FrankieSchedule (W9.1) — recurring prompts auto-run on cron.

Each schedule fires the stored prompt through FrankieService.chat with a
synthetic user (the creator) when next_run_at <= now. Output is delivered
to the chosen channel:
  - notification: family-wide in-app notification + push
  - chat: posted as a synthetic message in /chat (still in-app feed too)
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


VALID_CHANNELS = {"notification", "chat"}


class FrankieSchedule(Base):
    __tablename__ = "frankie_schedules"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('notification', 'chat')", name="chk_frankie_channel"
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    name = Column(String(120), nullable=False)
    prompt = Column(Text, nullable=False)
    cron_expr = Column(String(64), nullable=False)
    channel = Column(
        String(16), nullable=False, default="notification", server_default="notification"
    )
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
