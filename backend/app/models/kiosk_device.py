"""Kiosk device model (W3.3).

Lets a family register a static display (Echo Show, old iPad, Fire TV
Stick, hallway tablet) with a long-lived token. The token authorizes
read-only access to a family snapshot — no auth cookies, no CSRF — and
nothing else.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class KioskDevice(Base):
    __tablename__ = "kiosk_devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(120), nullable=False)
    token = Column(String(64), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_seen = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
