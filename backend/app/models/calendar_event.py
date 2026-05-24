"""Calendar event model (W2.1).

Family-scoped events. Source field tracks how the event was created so the UI
can render an icon (manual / OCR flyer / school import). Attendees is an
optional list of user UUIDs; null means "whole family".
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


VALID_SOURCES = {"manual", "ocr_flyer", "school_import", "recurring"}


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    family_id = Column(
        UUID(as_uuid=True),
        ForeignKey("families.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)
    start_ts = Column(DateTime(timezone=True), nullable=False)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    all_day = Column(Boolean, nullable=False, default=False, server_default="false")

    attendees = Column(JSONB, nullable=True)
    color = Column(String(24), nullable=True)

    source = Column(String(24), nullable=False, default="manual", server_default="manual")
    source_doc_url = Column(String(512), nullable=True)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Recurrence (W9.2). RRULE string (RFC 5545 subset) like
    # "FREQ=WEEKLY;BYDAY=MO,WE,FR" or "FREQ=DAILY;COUNT=10".
    # Master events store the rule; we expand virtual instances at
    # read time. recurrence_parent_id is reserved for future
    # one-off overrides that detach from the master.
    recurrence_rule = Column(String(256), nullable=True)
    recurrence_parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=True,
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
